from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.asset import Asset
from app.models.strategy import Strategy
from app.schemas.strategy import (
    StrategyCreate,
    StrategyItem,
    StrategyListResponse,
    StrategyUpdate,
)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


def _to_item(s: Strategy) -> StrategyItem:
    return StrategyItem(
        id=s.id,
        name=s.name,
        description=s.description,
        initial_capital=s.initial_capital,
        is_active=s.is_active,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("", response_model=StrategyListResponse)
async def list_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Strategy).order_by(Strategy.id))
    strategies = result.scalars().all()
    return StrategyListResponse(items=[_to_item(s) for s in strategies])


@router.post("", response_model=StrategyItem, status_code=201)
async def create_strategy(
    data: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    # 이름 중복 체크
    existing = await db.execute(select(Strategy).where(Strategy.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"이미 존재하는 전략 이름입니다: {data.name}",
        )

    strategy = Strategy(
        name=data.name,
        description=data.description,
        initial_capital=data.initial_capital,
    )
    db.add(strategy)
    await db.flush()

    # 초기 현금 자산 생성
    cash = Asset(
        strategy_id=strategy.id,
        stock_code=None,
        stock_name=None,
        quantity=1,
        unit_price=float(data.initial_capital),
        total_amount=float(data.initial_capital),
    )
    db.add(cash)
    await db.commit()
    await db.refresh(strategy)

    return _to_item(strategy)


@router.patch("/{strategy_id}", response_model=StrategyItem)
async def update_strategy(
    strategy_id: int,
    data: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    if data.description is not None:
        strategy.description = data.description
    if data.is_active is not None:
        strategy.is_active = data.is_active

    await db.commit()
    await db.refresh(strategy)
    return _to_item(strategy)
