"""이벤트 기반 트레이더 메인 프로세스.

이벤트 감지 → 퀀트 필터 → LLM 판단 → 매수/청산을 통합 실행하는
메인 루프. supervisord에 등록되어 장 운영 시간 동안 반복 실행된다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.strategy import Strategy
from app.models.system_parameter import SystemParameter
from app.models.prompt_template import PromptTemplate
from app.models.target_stock import TargetStock
from app.services.asset_manager import get_open_position
from app.services.param_helper import get_param
from app.services.circuit_breaker import check_circuit_breaker
from app.services.event_decision import make_event_decision
from app.services.event_detector import (
    detect_dart_events,
    detect_news_cluster_events,
    detect_volume_spike_events,
    expire_old_events,
)
from app.services.event_liquidator import run_liquidation_check
from app.services.position_sizer import execute_event_buy
from app.services.quant_filter import filter_events
from app.shared.telegram import send_message as send_telegram

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 매수 가능 마감 시각 (15:00) — 장 마감 30분 전 신규 매수 금지
BUY_CUTOFF_TIME = dt_time(15, 0)


# ---------------------------------------------------------------------------
# 장 운영 시간 체크
# ---------------------------------------------------------------------------


def is_market_open(
    now: datetime | None = None,
    market_start: str = "09:00",
    market_end: str = "15:20",
) -> bool:
    """현재 시각이 장 운영 시간인지 확인."""
    if now is None:
        now = datetime.now(KST)
    current_time = now.time() if now.tzinfo else now.time()
    try:
        start = dt_time.fromisoformat(market_start)
        end = dt_time.fromisoformat(market_end)
    except (ValueError, TypeError):
        start = dt_time(9, 0)
        end = dt_time(15, 20)
    return start <= current_time <= end


def is_buy_allowed(now: datetime | None = None) -> bool:
    """매수 가능 시간인지 확인 (15:00 이전)."""
    if now is None:
        now = datetime.now(KST)
    current_time = now.time() if now.tzinfo else now.time()
    return current_time < BUY_CUTOFF_TIME




# ---------------------------------------------------------------------------
# 보유 포지션 확인
# ---------------------------------------------------------------------------


async def has_position(db: AsyncSession, strategy_id: int) -> bool:
    """해당 전략에 보유 포지션이 있는지 확인."""
    position = await get_open_position(db, strategy_id)
    return position is not None


# ---------------------------------------------------------------------------
# 이벤트 감지 (1회)
# ---------------------------------------------------------------------------


async def detect_all_events(
    db: AsyncSession,
    redis_client=None,
) -> list:
    """세 가지 소스에서 이벤트를 감지한다 (1회)."""
    all_events = []
    results = await asyncio.gather(
        detect_dart_events(db, redis_client),
        detect_news_cluster_events(db, redis_client),
        detect_volume_spike_events(db, redis_client),
        return_exceptions=True,
    )
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            source_name = ["dart", "news_cluster", "volume_spike"][i]
            logger.error("이벤트 감지 실패 (%s): %s", source_name, r, exc_info=r)
        elif r:
            all_events.extend(r)

    # 오래된 이벤트 만료
    try:
        expired = await expire_old_events(db)
        if expired:
            logger.info("만료 이벤트 %d건 처리", expired)
    except Exception:
        logger.error("만료 이벤트 처리 실패", exc_info=True)

    return all_events


# ---------------------------------------------------------------------------
# 현재가 조회 (Redis 또는 DB 분봉)
# ---------------------------------------------------------------------------


async def _get_current_price_map(
    db: AsyncSession,
    strategy_id: int,
) -> dict[str, Decimal]:
    """보유 종목의 현재가 맵을 반환한다. Redis 또는 최신 분봉에서 조회."""
    from app.models.minute_candle import MinuteCandle

    price_map: dict[str, Decimal] = {}

    position = await get_open_position(db, strategy_id)
    if position is None or position.stock_code is None:
        return price_map

    stock_code = position.stock_code

    # Redis에서 먼저 시도
    try:
        from app.services.ws_collector import get_redis
        redis = await get_redis()
        key = f"ws:trade:{stock_code}"
        now_ts = datetime.now(KST).timestamp()
        five_min_ago = now_ts - 300
        raw_ticks = await redis.zrangebyscore(key, five_min_ago, now_ts)
        if raw_ticks:
            import json
            last_tick = json.loads(raw_ticks[-1] if isinstance(raw_ticks[-1], str) else raw_ticks[-1].decode("utf-8"))
            price = last_tick.get("price") or last_tick.get("stck_prpr")
            if price:
                price_map[stock_code] = Decimal(str(price))
                return price_map
    except Exception:
        logger.debug("Redis 현재가 조회 실패 (분봉 DB로 폴백)", exc_info=True)

    # DB 분봉에서 폴백
    result = await db.execute(
        select(MinuteCandle.close)
        .where(MinuteCandle.stock_code == stock_code)
        .order_by(MinuteCandle.minute_at.desc())
        .limit(1)
    )
    close_price = result.scalar_one_or_none()
    if close_price is not None:
        price_map[stock_code] = Decimal(str(close_price))

    return price_map


# ---------------------------------------------------------------------------
# 메인 루프
# ---------------------------------------------------------------------------


async def run_event_trader(
    strategy_name: str = "event_trader",
    db_session_factory=None,
    max_iterations: int | None = None,
) -> None:
    """이벤트 기반 트레이더 메인 루프.

    1. 전략 로드
    2. 장 운영 시간 체크 (09:00~15:20, 매수는 15:00까지)
    3. 서킷브레이커 체크
    4. 보유 포지션 있으면 -> 청산 체크
    5. 이벤트 감지 (1회)
    6. 감지된 이벤트 -> 퀀트 필터 -> LLM 판단 -> 매수 실행
    7. interval 대기 후 반복

    Args:
        strategy_name: 전략 이름
        db_session_factory: 테스트 시 세션 팩토리 주입
        max_iterations: 테스트 시 최대 루프 횟수 (None이면 무한)
    """
    if db_session_factory is None:
        from app.database import async_session
        db_session_factory = async_session

    # 전략 로드
    async with db_session_factory() as db:
        result = await db.execute(
            select(Strategy).where(
                Strategy.name == strategy_name,
                Strategy.is_active.is_(True),
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy is None:
            raise ValueError(f"활성 전략을 찾을 수 없습니다: {strategy_name}")
        strategy_id = strategy.id
        logger.info("이벤트 트레이더 시작: strategy_id=%d name=%s", strategy_id, strategy_name)

    await send_telegram(f"[이벤트 트레이더] 프로세스 시작 (전략: {strategy_name})")

    iteration = 0
    consecutive_llm_failures = 0

    try:
        while True:
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            async with db_session_factory() as db:
                interval = int(await get_param(db, "event_trader_interval", "30", strategy_id=strategy_id))
                market_start = await get_param(db, "market_start_time", "09:00", strategy_id=strategy_id)
                market_end = await get_param(db, "event_trader_market_end", "15:20", strategy_id=strategy_id)

                # 장 운영 시간 체크
                if not is_market_open(market_start=market_start, market_end=market_end):
                    logger.debug("장 운영 시간 외 (%s~%s)", market_start, market_end)
                    await asyncio.sleep(interval)
                    continue

                # 1. 청산 체크 (보유 포지션)
                try:
                    if await has_position(db, strategy_id):
                        price_map = await _get_current_price_map(db, strategy_id)
                        sell_order = await run_liquidation_check(
                            db, strategy_id, current_price_map=price_map
                        )
                        if sell_order is not None:
                            logger.info(
                                "청산 실행 완료: order_id=%s stock=%s",
                                sell_order.id, sell_order.stock_code,
                            )
                            await db.commit()
                except Exception:
                    logger.error("청산 체크 실패", exc_info=True)

                # 2. 서킷브레이커
                try:
                    cb = await check_circuit_breaker(db, strategy_id)
                    if cb.is_active:
                        logger.warning("서킷브레이커 활성: %s", cb.reason)
                        await asyncio.sleep(60)
                        continue
                except Exception:
                    logger.error("서킷브레이커 체크 실패", exc_info=True)

                # 매수 가능 시간 체크
                if not is_buy_allowed():
                    logger.debug("매수 마감 시간 (15:00 이후)")
                    await asyncio.sleep(interval)
                    continue

                # 이미 포지션 보유 중이면 신규 매수 스킵
                if await has_position(db, strategy_id):
                    logger.debug("이미 포지션 보유 중, 신규 매수 스킵")
                    await asyncio.sleep(interval)
                    continue

                # 3. 이벤트 감지
                try:
                    redis_client = None
                    try:
                        from app.services.ws_collector import get_redis
                        redis_client = await get_redis()
                    except Exception:
                        logger.debug("Redis 연결 실패 (DB 모드로 진행)")

                    events = await detect_all_events(db, redis_client)
                except Exception:
                    logger.error("이벤트 감지 실패", exc_info=True)
                    events = []

                if not events:
                    await asyncio.sleep(interval)
                    continue

                # 4. 퀀트 필터
                try:
                    passed, filtered = await filter_events(db, events, strategy_id)
                    if filtered:
                        logger.info(
                            "퀀트 필터: %d건 통과, %d건 필터링",
                            len(passed), len(filtered),
                        )
                except Exception:
                    logger.error("퀀트 필터 실패", exc_info=True)
                    passed = []

                # 5. LLM 판단 + 매수 (통과 이벤트 순회)
                for event in passed:
                    try:
                        decision, history = await make_event_decision(
                            db, event, strategy_id,
                        )
                        consecutive_llm_failures = 0

                        if decision.decision == "BUY":
                            order = await execute_event_buy(
                                db, strategy_id, event, decision, history,
                            )
                            if order is not None:
                                await db.commit()
                                await send_telegram(
                                    f"[이벤트 매수] {event.stock_name}({event.stock_code})\n"
                                    f"유형: {event.event_type}\n"
                                    f"가격: {order.result_price:,.0f}원 x {order.result_quantity}주\n"
                                    f"신뢰도: {decision.confidence:.0%}\n"
                                    f"근거: {decision.reasoning[:100]}"
                                )
                            break  # 1포지션 제한 -- 매수 후 루프 종료
                        else:
                            await db.commit()

                    except Exception:
                        consecutive_llm_failures += 1
                        logger.error("LLM 판단/매수 실패", exc_info=True)

                        if consecutive_llm_failures >= 3:
                            await send_telegram(
                                f"[이벤트 트레이더] LLM 호출 3회 연속 실패 (전략: {strategy_name})"
                            )
                            consecutive_llm_failures = 0
                        break

            await asyncio.sleep(interval)

    except Exception:
        logger.error("이벤트 트레이더 메인 루프 오류", exc_info=True)
        await send_telegram(f"[이벤트 트레이더] 프로세스 비정상 종료 (전략: {strategy_name})")
        raise
    finally:
        await send_telegram(f"[이벤트 트레이더] 프로세스 종료 (전략: {strategy_name})")


# ---------------------------------------------------------------------------
# 전략 초기화
# ---------------------------------------------------------------------------


async def init_event_strategy(
    db: AsyncSession,
    strategy_name: str = "event_trader",
    initial_capital: Decimal = Decimal("10000000"),
) -> Strategy:
    """이벤트 트레이더 전략을 초기화한다 (멱등).

    - Strategy 생성
    - 현금 Asset 생성
    - 기본 PromptTemplate 등록 (event_buy, event_sell)
    - 기본 SystemParameter 등록
    - TargetStock 복사 (default 전략에서)
    """
    # 1. Strategy 생성/조회
    result = await db.execute(
        select(Strategy).where(Strategy.name == strategy_name)
    )
    strategy = result.scalar_one_or_none()

    if strategy is None:
        strategy = Strategy(
            name=strategy_name,
            description="이벤트 기반 트레이딩 전략",
            initial_capital=initial_capital,
            is_active=True,
        )
        db.add(strategy)
        await db.flush()
        logger.info("전략 생성: id=%d name=%s", strategy.id, strategy.name)
    else:
        logger.info("전략 이미 존재: id=%d name=%s", strategy.id, strategy.name)

    strategy_id = strategy.id

    # 2. 현금 Asset 생성
    cash_result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code.is_(None),
        )
    )
    if cash_result.scalar_one_or_none() is None:
        cash = Asset(
            strategy_id=strategy_id,
            stock_code=None,
            stock_name=None,
            quantity=0,
            unit_price=0,
            total_amount=float(initial_capital),
        )
        db.add(cash)
        logger.info("현금 자산 생성: %s원", initial_capital)

    # 3. 기본 PromptTemplate 등록
    for prompt_type, content in _DEFAULT_PROMPTS.items():
        existing = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.strategy_id == strategy_id,
                PromptTemplate.prompt_type == prompt_type,
            )
        )
        if existing.scalar_one_or_none() is None:
            template = PromptTemplate(
                strategy_id=strategy_id,
                prompt_type=prompt_type,
                content=content,
                version=1,
                is_active=True,
            )
            db.add(template)
            logger.info("프롬프트 템플릿 등록: %s", prompt_type)

    # 4. 기본 SystemParameter 등록 (전략별)
    for key, value in _DEFAULT_PARAMS.items():
        existing = await db.execute(
            select(SystemParameter).where(
                SystemParameter.key == key,
                SystemParameter.strategy_id == strategy_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            param = SystemParameter(key=key, value=value, strategy_id=strategy_id)
            db.add(param)
            logger.info("시스템 파라미터 등록: %s=%s (strategy_id=%s)", key, value, strategy_id)

    # 5. TargetStock 복사 (default 전략에서)
    default_strategy_result = await db.execute(
        select(Strategy).where(Strategy.name == "default")
    )
    default_strategy = default_strategy_result.scalar_one_or_none()

    if default_strategy is not None:
        default_stocks_result = await db.execute(
            select(TargetStock).where(
                TargetStock.strategy_id == default_strategy.id,
                TargetStock.is_active.is_(True),
            )
        )
        default_stocks = default_stocks_result.scalars().all()

        for stock in default_stocks:
            existing = await db.execute(
                select(TargetStock).where(
                    TargetStock.strategy_id == strategy_id,
                    TargetStock.stock_code == stock.stock_code,
                )
            )
            if existing.scalar_one_or_none() is None:
                new_stock = TargetStock(
                    strategy_id=strategy_id,
                    stock_code=stock.stock_code,
                    stock_name=stock.stock_name,
                    dart_corp_code=stock.dart_corp_code,
                    is_active=True,
                )
                db.add(new_stock)
                logger.info("종목 복사: %s %s", stock.stock_code, stock.stock_name)

    await db.commit()
    await db.refresh(strategy)
    return strategy


# ---------------------------------------------------------------------------
# 기본 프롬프트 / 파라미터
# ---------------------------------------------------------------------------

_DEFAULT_PROMPTS: dict[str, str] = {
    "event_buy": (
        "당신은 이벤트 기반 한국 주식 트레이딩 전문가입니다.\n"
        "다음 이벤트와 시장 데이터를 분석하여 매수 여부를 판단하세요.\n\n"
        "현재 시각: {{ current_time }}\n"
        "이벤트 유형: {{ event_type }}\n"
        "종목: {{ stock_name }} ({{ stock_code }})\n\n"
        "=== 상세 컨텍스트 ===\n"
        "{{ context_json }}\n\n"
        "다음 JSON 형식으로 응답하세요:\n"
        '{\n'
        '  "decision": "BUY" 또는 "HOLD",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "reasoning": "판단 근거",\n'
        '  "target_return_pct": 목표수익률(%),\n'
        '  "stop_pct": 손절수준(%),\n'
        '  "holding_days": 예상보유기간(일),\n'
        '  "event_assessment": "이벤트 평가",\n'
        '  "risk_factors": ["리스크1", "리스크2"]\n'
        '}\n'
    ),
    "event_sell": (
        "당신은 이벤트 기반 트레이딩 전문가입니다.\n"
        "다음 보유 포지션의 청산 여부를 판단하세요.\n\n"
        "현재 시각: {{ current_time }}\n"
        "종목: {{ stock_name }} ({{ stock_code }})\n\n"
        "=== 상세 컨텍스트 ===\n"
        "{{ context_json }}\n\n"
        '다음 JSON 형식으로 응답하세요:\n'
        '{\n'
        '  "decision": "SELL" 또는 "HOLD",\n'
        '  "reasoning": "판단 근거"\n'
        '}\n'
    ),
}

_DEFAULT_PARAMS: dict[str, str] = {
    "event_trader_interval": "30",
    "event_trader_market_end": "15:20",
    "event_trader_sizing_mode": "fixed",
    "event_trader_fixed_amount": "500000",
    "event_trader_max_single_stock_pct": "0.20",
    "event_trader_min_cash_reserve_pct": "0.10",
    "event_trader_default_stop_pct": "-2",
    "cb_max_consecutive_losses": "3",
    "cb_daily_loss_limit_pct": "3.0",
    "cb_max_daily_trades": "5",
}
