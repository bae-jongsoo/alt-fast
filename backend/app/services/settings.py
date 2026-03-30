import re
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.market_snapshot import MarketSnapshot
from app.models.news import News
from app.models.prompt_template import PromptTemplate
from app.models.system_parameter import SystemParameter
from app.models.target_stock import TargetStock
from app.schemas.settings import (
    PromptTemplateItem,
    PromptTemplateListResponse,
    PromptTemplateUpdate,
    SystemParameterItem,
    SystemParameterListResponse,
    SystemParameterUpdate,
    TargetStockCreate,
    TargetStockItem,
    TargetStockListResponse,
)

# ──────────────────────────────────────────────
# 시스템 파라미터 기본값 / 범위 검증
# ──────────────────────────────────────────────

DEFAULT_PARAMETERS: dict[str, str] = {
    "trading_interval": "60",
    "market_start_time": "09:11",
    "market_end_time": "15:30",
    "news_interval": "300",
    "news_count": "10",
    "dart_interval": "600",
    "market_snapshot_interval": "60",
    "llm_trading": "high",
    "llm_review": "high",
    "llm_news": "normal",
    "llm_chatbot": "gemini",
}

PARAMETER_RULES: dict[str, dict] = {
    "trading_interval": {"min": 10, "max": 600, "type": "int"},
    "market_start_time": {"min": "08:00", "max": "10:00", "type": "time"},
    "market_end_time": {"min": "14:00", "max": "16:00", "type": "time"},
    "news_interval": {"min": 60, "max": 3600, "type": "int"},
    "news_count": {"min": 1, "max": 50, "type": "int"},
    "dart_interval": {"min": 60, "max": 7200, "type": "int"},
    "market_snapshot_interval": {"min": 10, "max": 600, "type": "int"},
    "llm_trading": {"options": ["normal", "high"], "type": "select"},
    "llm_review": {"options": ["normal", "high"], "type": "select"},
    "llm_news": {"options": ["normal", "high"], "type": "select"},
    "llm_chatbot": {"options": ["normal", "high", "gemini"], "type": "select"},
}

# 프롬프트 필수 변수 목록
PROMPT_VARIABLES: dict[str, list[str]] = {
    "buy": [
        "stock_code",
        "stock_name",
        "current_price",
        "market_snapshot",
        "news_summary",
        "dart_summary",
        "cash_balance",
    ],
    "sell": [
        "stock_code",
        "stock_name",
        "current_price",
        "market_snapshot",
        "news_summary",
        "dart_summary",
        "holding_quantity",
        "avg_buy_price",
    ],
}


def _validate_time_format(value: str) -> bool:
    return bool(re.match(r"^\d{2}:\d{2}$", value))


def _validate_parameter(key: str, value: str) -> None:
    rule = PARAMETER_RULES.get(key)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"알 수 없는 파라미터: {key}",
        )

    if rule["type"] == "int":
        try:
            int_val = int(value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}는 정수여야 합니다.",
            )
        if not (rule["min"] <= int_val <= rule["max"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}는 {rule['min']}~{rule['max']} 범위여야 합니다.",
            )

    elif rule["type"] == "time":
        if not _validate_time_format(value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}는 HH:MM 형식이어야 합니다.",
            )
        if not (rule["min"] <= value <= rule["max"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}는 {rule['min']}~{rule['max']} 범위여야 합니다.",
            )

    elif rule["type"] == "select":
        if value not in rule["options"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{key}는 {rule['options']} 중 하나여야 합니다.",
            )


# ──────────────────────────────────────────────
# 종목 설정
# ──────────────────────────────────────────────


async def get_stocks(db: AsyncSession, strategy_id: int | None = None) -> TargetStockListResponse:
    q = select(TargetStock).where(TargetStock.is_active.is_(True))
    if strategy_id is not None:
        q = q.where(TargetStock.strategy_id == strategy_id)
    result = await db.execute(q.order_by(TargetStock.stock_code.asc()))
    stocks = result.scalars().all()

    items: list[TargetStockItem] = []
    for s in stocks:
        items.append(
            TargetStockItem(
                id=s.id,
                stock_code=s.stock_code,
                stock_name=s.stock_name,
                dart_corp_code=s.dart_corp_code,
                is_active=s.is_active,
                created_at=s.created_at,
            )
        )

    return TargetStockListResponse(items=items)


async def create_stock(
    db: AsyncSession, data: TargetStockCreate, strategy_id: int | None = None
) -> TargetStockItem:
    # 중복 체크 (활성/비활성 모두, 전략 범위 내)
    q = select(TargetStock).where(TargetStock.stock_code == data.stock_code)
    if strategy_id is not None:
        q = q.where(TargetStock.strategy_id == strategy_id)
    existing = await db.execute(q)
    existing_stock = existing.scalar_one_or_none()

    if existing_stock is not None:
        if existing_stock.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"이미 등록된 종목코드입니다: {data.stock_code}",
            )
        # 비활성 종목이면 재활성화
        existing_stock.is_active = True
        existing_stock.stock_name = data.stock_name
        existing_stock.dart_corp_code = data.dart_corp_code
        await db.commit()
        await db.refresh(existing_stock)
        stock = existing_stock
    else:
        stock = TargetStock(
            strategy_id=strategy_id or data.strategy_id,
            stock_code=data.stock_code,
            stock_name=data.stock_name,
            dart_corp_code=data.dart_corp_code,
        )
        db.add(stock)
        await db.commit()
        await db.refresh(stock)

    return TargetStockItem(
        id=stock.id,
        stock_code=stock.stock_code,
        stock_name=stock.stock_name,
        dart_corp_code=stock.dart_corp_code,
        is_active=stock.is_active,
        created_at=stock.created_at,
    )


async def delete_stock(db: AsyncSession, stock_code: str, strategy_id: int | None = None) -> None:
    q = select(TargetStock).where(
        TargetStock.stock_code == stock_code,
        TargetStock.is_active.is_(True),
    )
    if strategy_id is not None:
        q = q.where(TargetStock.strategy_id == strategy_id)
    result = await db.execute(q)
    stock = result.scalar_one_or_none()
    if stock is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"종목을 찾을 수 없습니다: {stock_code}",
        )
    # soft delete
    stock.is_active = False
    await db.commit()


# ──────────────────────────────────────────────
# 프롬프트 설정
# ──────────────────────────────────────────────


async def get_prompts(db: AsyncSession, strategy_id: int | None = None) -> PromptTemplateListResponse:
    # 활성 프롬프트
    active_q = select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
    if strategy_id is not None:
        active_q = active_q.where(PromptTemplate.strategy_id == strategy_id)
    active_result = await db.execute(active_q)
    active_prompts = active_result.scalars().all()

    buy_prompt = None
    sell_prompt = None
    for p in active_prompts:
        item = PromptTemplateItem(
            id=p.id,
            prompt_type=p.prompt_type,
            content=p.content,
            version=p.version,
            is_active=p.is_active,
            created_at=p.created_at,
        )
        if p.prompt_type == "buy":
            buy_prompt = item
        elif p.prompt_type == "sell":
            sell_prompt = item

    # 버전 이력 (각 타입별 최근 10개)
    buy_v_q = select(PromptTemplate).where(PromptTemplate.prompt_type == "buy")
    sell_v_q = select(PromptTemplate).where(PromptTemplate.prompt_type == "sell")
    if strategy_id is not None:
        buy_v_q = buy_v_q.where(PromptTemplate.strategy_id == strategy_id)
        sell_v_q = sell_v_q.where(PromptTemplate.strategy_id == strategy_id)
    buy_versions_result = await db.execute(
        buy_v_q.order_by(PromptTemplate.version.desc()).limit(10)
    )
    sell_versions_result = await db.execute(
        sell_v_q.order_by(PromptTemplate.version.desc()).limit(10)
    )

    def to_items(rows) -> list[PromptTemplateItem]:
        return [
            PromptTemplateItem(
                id=r.id,
                prompt_type=r.prompt_type,
                content=r.content,
                version=r.version,
                is_active=r.is_active,
                created_at=r.created_at,
            )
            for r in rows
        ]

    return PromptTemplateListResponse(
        buy_prompt=buy_prompt,
        sell_prompt=sell_prompt,
        buy_versions=to_items(buy_versions_result.scalars().all()),
        sell_versions=to_items(sell_versions_result.scalars().all()),
    )


async def update_prompt(
    db: AsyncSession, prompt_type: str, data: PromptTemplateUpdate, strategy_id: int | None = None
) -> PromptTemplateItem:
    if prompt_type not in ("buy", "sell"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prompt_type은 'buy' 또는 'sell'이어야 합니다.",
        )

    # 기존 활성 프롬프트 비활성화 및 최대 버전 조회
    current_q = select(PromptTemplate).where(
        PromptTemplate.prompt_type == prompt_type,
        PromptTemplate.is_active.is_(True),
    )
    max_q = select(func.max(PromptTemplate.version)).where(
        PromptTemplate.prompt_type == prompt_type
    )
    if strategy_id is not None:
        current_q = current_q.where(PromptTemplate.strategy_id == strategy_id)
        max_q = max_q.where(PromptTemplate.strategy_id == strategy_id)

    current = await db.execute(current_q)
    current_prompt = current.scalar_one_or_none()

    max_version_result = await db.execute(max_q)
    max_version = max_version_result.scalar() or 0

    if current_prompt:
        current_prompt.is_active = False

    new_prompt = PromptTemplate(
        strategy_id=strategy_id or current_prompt.strategy_id,
        prompt_type=prompt_type,
        content=data.content,
        version=max_version + 1,
        is_active=True,
    )
    db.add(new_prompt)
    await db.commit()
    await db.refresh(new_prompt)

    return PromptTemplateItem(
        id=new_prompt.id,
        prompt_type=new_prompt.prompt_type,
        content=new_prompt.content,
        version=new_prompt.version,
        is_active=new_prompt.is_active,
        created_at=new_prompt.created_at,
    )


def get_prompt_variables() -> dict[str, list[str]]:
    return PROMPT_VARIABLES


# ──────────────────────────────────────────────
# 시스템 파라미터
# ──────────────────────────────────────────────


async def get_parameters(db: AsyncSession) -> SystemParameterListResponse:
    result = await db.execute(
        select(SystemParameter)
        .where(SystemParameter.strategy_id.is_(None))
        .order_by(SystemParameter.key.asc())
    )
    params = result.scalars().all()

    return SystemParameterListResponse(
        items=[
            SystemParameterItem(
                key=p.key,
                value=p.value,
                updated_at=p.updated_at,
            )
            for p in params
        ]
    )


async def update_parameters(
    db: AsyncSession, data: SystemParameterUpdate
) -> SystemParameterListResponse:
    for key, value in data.parameters.items():
        _validate_parameter(key, value)

    for key, value in data.parameters.items():
        result = await db.execute(
            select(SystemParameter).where(
                SystemParameter.key == key,
                SystemParameter.strategy_id.is_(None),
            )
        )
        param = result.scalar_one_or_none()
        if param:
            param.value = value
            param.updated_at = datetime.utcnow()
        else:
            db.add(SystemParameter(key=key, value=value))

    await db.commit()
    return await get_parameters(db)


async def reset_parameters(db: AsyncSession) -> SystemParameterListResponse:
    for key, default_value in DEFAULT_PARAMETERS.items():
        result = await db.execute(
            select(SystemParameter).where(
                SystemParameter.key == key,
                SystemParameter.strategy_id.is_(None),
            )
        )
        param = result.scalar_one_or_none()
        if param:
            param.value = default_value
            param.updated_at = datetime.utcnow()
        else:
            db.add(SystemParameter(key=key, value=default_value))

    await db.commit()
    return await get_parameters(db)


async def seed_default_parameters(db: AsyncSession) -> None:
    """앱 시작 시 기본 파라미터가 없으면 생성"""
    for key, default_value in DEFAULT_PARAMETERS.items():
        result = await db.execute(
            select(SystemParameter).where(
                SystemParameter.key == key,
                SystemParameter.strategy_id.is_(None),
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(SystemParameter(key=key, value=default_value))
    await db.commit()
