"""가상매수/매도 로직 — Django ORM → SQLAlchemy async 포팅."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

COMMISSION_RATE = Decimal("0.00015")      # 증권사 수수료 0.015% (매수/매도 각각)
TRANSACTION_TAX_RATE = Decimal("0.002")   # 증권거래세 0.2% (매도 시에만, KOSPI)


async def get_cash_asset(db: AsyncSession, strategy_id: int) -> Asset:
    """현금 자산(stock_code IS NULL) 단일 행을 반환한다."""
    result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code.is_(None),
        )
    )
    rows = result.scalars().all()
    if len(rows) != 1:
        raise RuntimeError(f"현금 row는 정확히 1건이어야 합니다 (strategy_id={strategy_id})")
    return rows[0]


async def get_open_position(db: AsyncSession, strategy_id: int) -> Asset | None:
    """보유 종목(stock_code IS NOT NULL)을 반환한다. 없으면 None."""
    result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code.isnot(None),
        )
    )
    positions = result.scalars().all()
    if len(positions) > 1:
        raise RuntimeError(f"보유 종목은 동시에 1건만 허용됩니다 (strategy_id={strategy_id})")
    if not positions:
        return None
    return positions[0]


async def apply_virtual_buy(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str,
    stock_name: str,
    price: Decimal,
    quantity: int,
) -> tuple[Asset, Asset]:
    """가상 매수: 현금 차감(수수료 포함) + 포지션 생성/추가."""
    buy_amount = price * quantity
    commission = buy_amount * COMMISSION_RATE
    total_deduct = buy_amount + commission

    cash = await get_cash_asset(db, strategy_id)
    position = await get_open_position(db, strategy_id)

    if position is not None and position.stock_code != stock_code:
        raise ValueError("다른 종목을 이미 보유 중입니다")
    if Decimal(str(cash.total_amount)) < total_deduct:
        raise ValueError("현금이 부족합니다 (수수료 포함)")

    cash.total_amount = float(Decimal(str(cash.total_amount)) - total_deduct)
    cash.unit_price = cash.total_amount

    if position is None:
        position = Asset(
            strategy_id=strategy_id,
            stock_code=stock_code,
            stock_name=stock_name,
            quantity=quantity,
            unit_price=float(price),
            total_amount=float(buy_amount),
        )
        db.add(position)
    else:
        new_quantity = position.quantity + quantity
        new_total = Decimal(str(position.total_amount)) + buy_amount
        position.quantity = new_quantity
        position.total_amount = float(new_total)
        position.unit_price = float(new_total / new_quantity)

    await db.flush()
    return cash, position


async def apply_virtual_sell(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str,
    price: Decimal,
    quantity: int,
) -> tuple[Asset, Asset]:
    """가상 매도: 현금 증가(수수료+거래세 차감) + 포지션 감소/삭제."""
    sell_amount = price * quantity
    commission = sell_amount * COMMISSION_RATE
    tax = sell_amount * TRANSACTION_TAX_RATE
    net_receive = sell_amount - commission - tax

    cash = await get_cash_asset(db, strategy_id)
    position = await get_open_position(db, strategy_id)

    if position is None or position.stock_code != stock_code:
        raise ValueError("해당 종목을 보유하고 있지 않습니다")
    if quantity > position.quantity:
        raise ValueError("보유 수량을 초과해 매도할 수 없습니다")

    cash.total_amount = float(Decimal(str(cash.total_amount)) + net_receive)
    cash.unit_price = cash.total_amount

    remaining_quantity = position.quantity - quantity
    if remaining_quantity == 0:
        await db.delete(position)
        position.quantity = 0
        position.total_amount = 0
    else:
        position.quantity = remaining_quantity
        position.total_amount = float(Decimal(str(position.unit_price)) * remaining_quantity)

    await db.flush()
    return cash, position
