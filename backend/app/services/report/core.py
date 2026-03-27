"""보고서 서비스 코어 — 매매 타임라인, 승률/손익비, 워터폴 데이터."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time as dt_time

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.schemas.report import (
    DailyReportSummary,
    EntrySpeedBreakdown,
    TradeTimelineItem,
    TradeWaterfallItem,
    WinLossStats,
)


def _date_range(target: date) -> tuple[datetime, datetime]:
    """날짜를 naive datetime 범위(KST 기준)로 변환."""
    start = datetime(target.year, target.month, target.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


def _classify_holding_time(seconds: float) -> str:
    """보유시간 구간 분류."""
    if seconds <= 600:  # 10분
        return "초단타"
    elif seconds <= 1800:  # 30분
        return "단타"
    elif seconds <= 3600:  # 1시간
        return "스윙단타"
    else:
        return "중기"


def _classify_time_zone(dt: datetime) -> str:
    """시간대 태그 부여."""
    t = dt.time()
    if dt_time(9, 11) <= t < dt_time(9, 30):
        return "장초반"
    elif dt_time(9, 30) <= t < dt_time(11, 30):
        return "오전장"
    elif dt_time(11, 30) <= t < dt_time(13, 0):
        return "점심"
    elif dt_time(13, 0) <= t < dt_time(14, 30):
        return "오후장"
    elif dt_time(14, 30) <= t < dt_time(15, 20):
        return "마감접근"
    elif dt_time(15, 20) <= t <= dt_time(15, 30):
        return "동시호가"
    else:
        return "장외"


async def get_trade_timeline(
    db: AsyncSession, target_date: date
) -> list[TradeTimelineItem]:
    """매매 타임라인 조회."""
    start, end = _date_range(target_date)

    BuyOrder = aliased(OrderHistory)
    Decision = aliased(DecisionHistory)

    stmt = (
        select(OrderHistory, BuyOrder, Decision)
        .outerjoin(BuyOrder, OrderHistory.buy_order_id == BuyOrder.id)
        .outerjoin(
            Decision, OrderHistory.decision_history_id == Decision.id
        )
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
            )
        )
        .order_by(OrderHistory.result_executed_at.asc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    items: list[TradeTimelineItem] = []
    for sell, buy, decision in rows:
        buy_executed_at = buy.result_executed_at if buy else None
        sell_executed_at = sell.result_executed_at

        holding_seconds: float | None = None
        holding_category: str | None = None
        if buy_executed_at and sell_executed_at:
            delta = (sell_executed_at - buy_executed_at).total_seconds()
            holding_seconds = delta
            holding_category = _classify_holding_time(delta)

        time_zone_tag: str | None = None
        if sell_executed_at:
            time_zone_tag = _classify_time_zone(sell_executed_at)

        # 진입 속도 3구간
        entry_speed: EntrySpeedBreakdown | None = None
        if buy and decision:
            llm_ms = decision.processing_time_ms if decision else None

            decision_to_order_ms: float | None = None
            if decision and buy.order_placed_at and decision.created_at:
                decision_to_order_ms = (
                    buy.order_placed_at - decision.created_at
                ).total_seconds() * 1000

            order_to_exec_ms: float | None = None
            if buy.order_placed_at and buy_executed_at:
                order_to_exec_ms = (
                    buy_executed_at - buy.order_placed_at
                ).total_seconds() * 1000

            entry_speed = EntrySpeedBreakdown(
                llm_processing_ms=llm_ms,
                decision_to_order_ms=decision_to_order_ms,
                order_to_execution_ms=order_to_exec_ms,
            )

        items.append(
            TradeTimelineItem(
                sell_order_id=sell.id,
                buy_order_id=sell.buy_order_id,
                stock_code=sell.stock_code,
                stock_name=sell.stock_name,
                buy_price=float(buy.result_price) if buy else 0.0,
                sell_price=float(sell.result_price),
                quantity=sell.result_quantity,
                buy_executed_at=buy_executed_at,
                sell_executed_at=sell_executed_at,
                holding_seconds=holding_seconds,
                holding_category=holding_category,
                time_zone_tag=time_zone_tag,
                profit_loss_net=(
                    float(sell.profit_loss_net)
                    if sell.profit_loss_net is not None
                    else None
                ),
                entry_speed=entry_speed,
            )
        )

    return items


async def get_win_loss_stats(
    db: AsyncSession, target_date: date
) -> WinLossStats:
    """승률/손익비/기대값 계산."""
    start, end = _date_range(target_date)

    stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
                OrderHistory.profit_loss_net.is_not(None),
            )
        )
        .order_by(OrderHistory.result_executed_at.asc())
    )

    result = await db.execute(stmt)
    sells = list(result.scalars().all())

    if not sells:
        return WinLossStats()

    profits = [float(s.profit_loss_net) for s in sells if float(s.profit_loss_net) >= 0]
    losses = [float(s.profit_loss_net) for s in sells if float(s.profit_loss_net) < 0]

    total = len(sells)
    win_count = len(profits)
    loss_count = len(losses)
    win_rate = (win_count / total) * 100 if total > 0 else 0.0

    avg_profit = sum(profits) / win_count if win_count > 0 else 0.0
    avg_loss = sum(losses) / loss_count if loss_count > 0 else 0.0

    # 손익비
    profit_loss_ratio: float | None = None
    if avg_loss != 0:
        profit_loss_ratio = abs(avg_profit / avg_loss)

    # 기대값
    loss_rate = (loss_count / total) * 100 if total > 0 else 0.0
    expected_value = (win_rate / 100 * avg_profit) - (loss_rate / 100 * abs(avg_loss))

    # Profit Factor
    total_profit = sum(profits)
    total_loss = abs(sum(losses))
    profit_factor: float | None = None
    if total_loss > 0:
        profit_factor = total_profit / total_loss
    elif total_profit > 0:
        profit_factor = float("inf")

    # 최대 연속 승/패
    max_consec_wins = 0
    max_consec_losses = 0
    current_wins = 0
    current_losses = 0
    for s in sells:
        pnl = float(s.profit_loss_net)
        if pnl >= 0:
            current_wins += 1
            current_losses = 0
            max_consec_wins = max(max_consec_wins, current_wins)
        else:
            current_losses += 1
            current_wins = 0
            max_consec_losses = max(max_consec_losses, current_losses)

    return WinLossStats(
        total_trades=total,
        winning_trades=win_count,
        losing_trades=loss_count,
        win_rate=win_rate,
        avg_profit=avg_profit,
        avg_loss=avg_loss,
        profit_loss_ratio=profit_loss_ratio,
        expected_value=expected_value,
        profit_factor=profit_factor,
        effective_profit_loss_ratio=profit_loss_ratio,  # 세후 기준이므로 동일
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
    )


async def get_trade_waterfall(
    db: AsyncSession, target_date: date
) -> list[TradeWaterfallItem]:
    """거래별 손익 워터폴 + MDD 계산."""
    start, end = _date_range(target_date)

    stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
                OrderHistory.profit_loss_net.is_not(None),
            )
        )
        .order_by(OrderHistory.result_executed_at.asc())
    )

    result = await db.execute(stmt)
    sells = list(result.scalars().all())

    items: list[TradeWaterfallItem] = []
    cumulative = 0.0
    for i, s in enumerate(sells, start=1):
        pnl = float(s.profit_loss_net)
        cumulative += pnl
        items.append(
            TradeWaterfallItem(
                trade_number=i,
                stock_name=s.stock_name,
                stock_code=s.stock_code,
                profit_loss_net=pnl,
                cumulative_profit_loss=cumulative,
                executed_at=s.result_executed_at,
            )
        )

    return items


def calculate_mdd(
    waterfall: list[TradeWaterfallItem],
) -> tuple[float | None, float | None]:
    """누적 손익 기반 일중 MDD 및 회복 시간(초) 계산.

    Returns:
        (mdd, recovery_seconds)
    """
    if not waterfall:
        return None, None

    peak = 0.0
    mdd = 0.0
    mdd_peak_idx = 0
    mdd_trough_idx = 0

    for i, item in enumerate(waterfall):
        cum = item.cumulative_profit_loss
        if cum > peak:
            peak = cum
        drawdown = peak - cum
        if drawdown > mdd:
            mdd = drawdown
            mdd_trough_idx = i
            # Find the peak index just before this trough
            for j in range(i, -1, -1):
                if waterfall[j].cumulative_profit_loss >= peak:
                    mdd_peak_idx = j
                    break

    if mdd == 0.0:
        return 0.0, None

    # MDD 회복 시간: MDD 발생 시점 → 누적 손익이 이전 고점 회복한 시점
    recovery_seconds: float | None = None
    peak_at_mdd = waterfall[mdd_peak_idx].cumulative_profit_loss
    mdd_trough_time = waterfall[mdd_trough_idx].executed_at

    for item in waterfall[mdd_trough_idx + 1 :]:
        if item.cumulative_profit_loss >= peak_at_mdd:
            if mdd_trough_time and item.executed_at:
                recovery_seconds = (
                    item.executed_at - mdd_trough_time
                ).total_seconds()
            break

    return mdd, recovery_seconds


async def _get_starting_cash(db: AsyncSession, target_date: date) -> float | None:
    """해당일 시작 현금 조회 (assets 테이블에서 stock_code IS NULL인 현금 잔고)."""
    start, end = _date_range(target_date)

    # 해당 날짜의 가장 이른 현금 자산 레코드
    stmt = (
        select(Asset.total_amount)
        .where(
            and_(
                Asset.stock_code.is_(None),
                Asset.updated_at >= start,
                Asset.updated_at < end,
            )
        )
        .order_by(Asset.updated_at.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        return float(row)

    # fallback: 전날 마지막 현금 레코드
    stmt2 = (
        select(Asset.total_amount)
        .where(Asset.stock_code.is_(None))
        .where(Asset.updated_at < start)
        .order_by(Asset.updated_at.desc())
        .limit(1)
    )
    result2 = await db.execute(stmt2)
    row2 = result2.scalar_one_or_none()
    return float(row2) if row2 is not None else None


async def get_daily_summary(
    db: AsyncSession, target_date: date
) -> DailyReportSummary:
    """전체 Executive Summary 생성."""
    stats = await get_win_loss_stats(db, target_date)
    waterfall = await get_trade_waterfall(db, target_date)

    mdd, mdd_recovery = calculate_mdd(waterfall)

    net_pnl = sum(item.profit_loss_net for item in waterfall)
    starting_cash = await _get_starting_cash(db, target_date)

    return_rate: float | None = None
    if starting_cash and starting_cash > 0:
        return_rate = (net_pnl / starting_cash) * 100

    return DailyReportSummary(
        date=target_date.isoformat(),
        net_profit_loss=net_pnl,
        return_rate=return_rate,
        total_trades=stats.total_trades,
        win_rate=stats.win_rate,
        expected_value=stats.expected_value,
        profit_factor=stats.profit_factor,
        intraday_mdd=mdd,
        mdd_recovery_seconds=mdd_recovery,
        starting_cash=starting_cash,
    )
