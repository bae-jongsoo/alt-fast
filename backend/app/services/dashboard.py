from datetime import datetime, timedelta, timezone
from decimal import Decimal

KST = timezone(timedelta(hours=9))

COMMISSION_RATE = Decimal("0.00015")      # 0.015%
TRANSACTION_TAX_RATE = Decimal("0.002")   # 0.2%

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.news import News
from app.models.order_history import OrderHistory
from app.schemas.dashboard import (
    DashboardResponse,
    HoldingStock,
    RecentError,
    RecentOrder,
    SummaryCard,
    SystemStatus,
    TradingCycleSummary,
)

SYSTEM_THRESHOLDS = {
    "trader": 120,
    "market": 120,
    "news": 600,
    "dart": 1200,
    "ws": 120,
}


async def _get_latest_price(db: AsyncSession, stock_code: str) -> float:
    result = await db.execute(
        select(MinuteCandle.close)
        .where(MinuteCandle.stock_code == stock_code)
        .order_by(MinuteCandle.minute_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return float(row) if row is not None else 0.0


async def _get_summary(db: AsyncSession) -> SummaryCard:
    now = datetime.now(KST).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 현금
    cash_row = await db.execute(
        select(Asset).where(Asset.stock_code.is_(None)).limit(1)
    )
    cash_asset = cash_row.scalar_one_or_none()
    cash_balance = float(cash_asset.total_amount) if cash_asset else 0.0

    # 보유종목 평가액
    holdings_result = await db.execute(
        select(Asset).where(Asset.stock_code.isnot(None))
    )
    holdings = holdings_result.scalars().all()

    eval_total = 0.0
    for h in holdings:
        price = await _get_latest_price(db, h.stock_code)
        eval_total += price * h.quantity

    total_asset_value = cash_balance + eval_total

    # 오늘 실현손익
    pnl_result = await db.execute(
        select(func.coalesce(func.sum(OrderHistory.profit_loss), 0))
        .where(
            OrderHistory.order_type == "SELL",
            OrderHistory.created_at >= today_start,
        )
    )
    today_realized_pnl = float(pnl_result.scalar())

    # 오늘 거래 횟수
    buy_count_result = await db.execute(
        select(func.count())
        .select_from(OrderHistory)
        .where(OrderHistory.order_type == "BUY", OrderHistory.created_at >= today_start)
    )
    sell_count_result = await db.execute(
        select(func.count())
        .select_from(OrderHistory)
        .where(OrderHistory.order_type == "SELL", OrderHistory.created_at >= today_start)
    )
    today_buy = buy_count_result.scalar() or 0
    today_sell = sell_count_result.scalar() or 0

    # 전일 대비 (간단 구현: 전일 데이터 없으면 None)
    return SummaryCard(
        total_asset_value=total_asset_value,
        total_asset_change=None,
        total_asset_change_rate=None,
        cash_balance=cash_balance,
        today_realized_pnl=today_realized_pnl,
        today_trade_count=today_buy + today_sell,
        today_buy_count=today_buy,
        today_sell_count=today_sell,
    )


async def _get_holdings(db: AsyncSession) -> list[HoldingStock]:
    result = await db.execute(
        select(Asset).where(Asset.stock_code.isnot(None))
    )
    holdings = result.scalars().all()

    items = []
    for h in holdings:
        current_price = await _get_latest_price(db, h.stock_code)
        avg_price = float(h.unit_price)
        eval_pnl = (current_price - avg_price) * h.quantity if avg_price > 0 else 0.0
        profit_rate = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
        # 세후 수익률: 매수 수수료 + 매도 수수료 + 거래세
        buy_cost = Decimal(str(avg_price)) * h.quantity
        sell_cost = Decimal(str(current_price)) * h.quantity
        total_fee = buy_cost * COMMISSION_RATE + sell_cost * COMMISSION_RATE + sell_cost * TRANSACTION_TAX_RATE
        profit_loss_net = Decimal(str(eval_pnl)) - total_fee
        profit_rate_net = float(profit_loss_net / buy_cost * 100) if buy_cost > 0 else 0.0
        items.append(HoldingStock(
            stock_code=h.stock_code,
            stock_name=h.stock_name or "",
            quantity=h.quantity,
            avg_buy_price=avg_price,
            current_price=current_price,
            eval_pnl=eval_pnl,
            profit_rate=round(profit_rate, 2),
            profit_rate_net=round(profit_rate_net, 2),
        ))
    return items


async def _get_system_status(db: AsyncSession) -> list[SystemStatus]:
    now = datetime.now(KST).replace(tzinfo=None)

    model_map = {
        "trader": (DecisionHistory, DecisionHistory.created_at),
        "market": (MarketSnapshot, MarketSnapshot.created_at),
        "news": (News, News.created_at),
        "dart": (DartDisclosure, DartDisclosure.created_at),
        "ws": (MinuteCandle, MinuteCandle.minute_at),
    }

    statuses = []
    for name, (model, col) in model_map.items():
        result = await db.execute(select(func.max(col)))
        last_at = result.scalar_one_or_none()
        threshold = SYSTEM_THRESHOLDS[name]

        if last_at is None:
            status = "stopped"
        else:
            diff = (now - last_at).total_seconds()
            if diff < threshold:
                status = "normal"
            elif diff < threshold * 3:
                status = "delayed"
            else:
                status = "stopped"

        statuses.append(SystemStatus(
            name=name,
            status=status,
            last_active_at=last_at,
            threshold_seconds=threshold,
        ))
    return statuses


async def _get_trading_summary(db: AsyncSession) -> TradingCycleSummary:
    now = datetime.now(KST).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(DecisionHistory.decision == "BUY").label("buy"),
            func.count().filter(DecisionHistory.decision == "SELL").label("sell"),
            func.count().filter(DecisionHistory.decision == "HOLD").label("hold"),
            func.count().filter(DecisionHistory.is_error.is_(True)).label("errors"),
        )
        .select_from(DecisionHistory)
        .where(DecisionHistory.created_at >= today_start)
    )
    row = result.one()
    return TradingCycleSummary(
        total_decisions=row.total,
        buy_count=row.buy,
        sell_count=row.sell,
        hold_count=row.hold,
        error_count=row.errors,
    )


async def _get_recent_orders(db: AsyncSession) -> list[RecentOrder]:
    result = await db.execute(
        select(OrderHistory)
        .order_by(OrderHistory.created_at.desc())
        .limit(5)
    )
    orders = result.scalars().all()
    return [
        RecentOrder(
            id=o.id,
            created_at=o.created_at,
            stock_name=o.stock_name or "",
            order_type=o.order_type,
            order_price=float(o.order_price),
            quantity=o.order_quantity,
            profit_loss=float(o.profit_loss) if o.profit_loss is not None else None,
            profit_rate=float(o.profit_rate) if o.profit_rate is not None else None,
            profit_rate_net=float(o.profit_rate_net) if o.profit_rate_net is not None else None,
        )
        for o in orders
    ]


async def _get_recent_errors(db: AsyncSession) -> list[RecentError]:
    result = await db.execute(
        select(DecisionHistory)
        .where(DecisionHistory.is_error.is_(True))
        .order_by(DecisionHistory.created_at.desc())
        .limit(3)
    )
    errors = result.scalars().all()
    return [
        RecentError(
            id=e.id,
            created_at=e.created_at,
            error_message=e.error_message or "",
        )
        for e in errors
    ]


async def get_dashboard(db: AsyncSession) -> DashboardResponse:
    summary = await _get_summary(db)
    holdings = await _get_holdings(db)
    system_status = await _get_system_status(db)
    trading_summary = await _get_trading_summary(db)
    recent_orders = await _get_recent_orders(db)
    recent_errors = await _get_recent_errors(db)

    return DashboardResponse(
        summary=summary,
        holdings=holdings,
        system_status=system_status,
        trading_summary=trading_summary,
        recent_orders=recent_orders,
        recent_errors=recent_errors,
        last_updated_at=datetime.now(KST).replace(tzinfo=None),
    )
