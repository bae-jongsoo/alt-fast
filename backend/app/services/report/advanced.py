"""보고서 서비스 고급 분석 — LLM 판단근거 복기, 호가 활용도 검증."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, and_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.schemas.report import (
    LLMSourceReview,
    LLMSourceStats,
    OrderbookAnalysis,
    OrderbookSignal,
)

logger = logging.getLogger(__name__)


# ── 유틸리티 ─────────────────────────────────────────────────────


def _date_range(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


# ── #7 LLM 판단근거 복기 ─────────────────────────────────────────


def _extract_source_types(parsed_decision: dict | None) -> set[str]:
    """parsed_decision에서 소스 type 집합을 추출한다."""
    if not parsed_decision:
        return set()
    try:
        decision_block = parsed_decision.get("decision", {})
        if not decision_block:
            return set()
        sources = decision_block.get("sources", [])
        if not sources:
            return set()
        return {s.get("type", "") for s in sources if s.get("type")}
    except (AttributeError, TypeError):
        return set()


async def analyze_llm_sources(
    db: AsyncSession, target_date: date
) -> LLMSourceReview:
    """해당일 LLM 판단근거 복기 분석."""
    start, end = _date_range(target_date)

    # 1. 해당일 BUY 판단 중 is_error=False인 것만 조회
    stmt = (
        select(DecisionHistory)
        .where(
            and_(
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
                DecisionHistory.decision == "BUY",
                DecisionHistory.is_error == False,  # noqa: E712
            )
        )
        .order_by(DecisionHistory.created_at)
    )
    result = await db.execute(stmt)
    decisions = result.scalars().all()

    if not decisions:
        return LLMSourceReview(total_buy_decisions=0, data_count=0)

    # 2. 각 판단에 대해 order_histories 매칭하여 승패 판정
    #    decision_history_id -> OrderHistory (BUY) -> 해당 buy_order_id를 가진 SELL의 profit_loss_net
    decision_ids = [d.id for d in decisions]

    # BUY 주문 조회
    buy_orders_stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.decision_history_id.in_(decision_ids),
                OrderHistory.order_type == "BUY",
            )
        )
    )
    buy_result = await db.execute(buy_orders_stmt)
    buy_orders = buy_result.scalars().all()
    buy_order_map: dict[int, OrderHistory] = {
        bo.decision_history_id: bo for bo in buy_orders
    }

    # SELL 주문 조회 (buy_order_id로 매칭)
    buy_order_ids = [bo.id for bo in buy_orders]
    sell_pnl_map: dict[int, float] = {}
    if buy_order_ids:
        sell_orders_stmt = (
            select(OrderHistory)
            .where(
                and_(
                    OrderHistory.buy_order_id.in_(buy_order_ids),
                    OrderHistory.order_type == "SELL",
                )
            )
        )
        sell_result = await db.execute(sell_orders_stmt)
        sell_orders = sell_result.scalars().all()
        for so in sell_orders:
            if so.buy_order_id is not None and so.profit_loss_net is not None:
                sell_pnl_map[so.buy_order_id] = float(so.profit_loss_net)

    # 3. 판단별 (소스 집합, 승패) 리스트 구성
    all_source_types: set[str] = set()
    decision_records: list[tuple[set[str], bool]] = []

    for dec in decisions:
        buy_order = buy_order_map.get(dec.id)
        if not buy_order:
            continue

        pnl = sell_pnl_map.get(buy_order.id)
        if pnl is None:
            continue

        sources = _extract_source_types(dec.parsed_decision)
        is_win = pnl > 0
        all_source_types.update(sources)
        decision_records.append((sources, is_win))

    if not decision_records:
        return LLMSourceReview(
            total_buy_decisions=len(decisions), data_count=0
        )

    # 4. 소스 type별 집계
    source_stats_list: list[LLMSourceStats] = []

    for stype in sorted(all_source_types):
        with_source = [(s, w) for s, w in decision_records if stype in s]
        without_source = [(s, w) for s, w in decision_records if stype not in s]

        wins_with = sum(1 for _, w in with_source if w)
        wins_without = sum(1 for _, w in without_source if w)

        wr_with = (wins_with / len(with_source) * 100) if with_source else 0.0
        wr_without = (
            (wins_without / len(without_source) * 100) if without_source else 0.0
        )

        source_stats_list.append(
            LLMSourceStats(
                source_type=stype,
                mention_count=len(with_source),
                win_rate_with=round(wr_with, 1),
                win_rate_without=round(wr_without, 1),
            )
        )

    # 5. 가장 적중률 높은/낮은 소스
    best_source = None
    worst_source = None
    if source_stats_list:
        best = max(source_stats_list, key=lambda x: x.win_rate_with)
        worst = min(source_stats_list, key=lambda x: x.win_rate_with)
        best_source = best.source_type
        worst_source = worst.source_type

    return LLMSourceReview(
        source_stats=source_stats_list,
        best_source=best_source,
        worst_source=worst_source,
        total_buy_decisions=len(decisions),
        data_count=len(decision_records),
    )


# ── #11 호가 활용도 검증 ──────────────────────────────────────────


def _compute_orderbook_signal(
    snapshot: OrderbookSnapshot,
    prev_snapshot: OrderbookSnapshot | None = None,
) -> OrderbookSignal:
    """호가 스냅샷에서 5가지 가공 지표를 계산한다."""
    total_bid = snapshot.total_bid_volume or 0
    total_ask = snapshot.total_ask_volume or 0

    # 수급 비율
    supply_demand_ratio = (
        total_bid / total_ask if total_ask > 0 else None
    )

    # 스프레드 비율
    ask1 = snapshot.ask_price1
    bid1 = snapshot.bid_price1
    mid = (ask1 + bid1) / 2 if (ask1 + bid1) > 0 else 0
    spread_ratio = ((ask1 - bid1) / mid * 100) if mid > 0 else None

    # 1호가 집중도
    bid1_concentration = (
        snapshot.bid_volume1 / total_bid if total_bid > 0 else None
    )

    # 매도벽 존재 여부: 매도 호가 잔량 중 평균의 3배 이상인 것이 있는지
    ask_volumes = [
        snapshot.ask_volume1,
        snapshot.ask_volume2,
        snapshot.ask_volume3,
        snapshot.ask_volume4,
        snapshot.ask_volume5,
    ]
    avg_ask_vol = sum(ask_volumes) / len(ask_volumes) if ask_volumes else 0
    sell_wall_exists = any(v >= avg_ask_vol * 3 for v in ask_volumes) if avg_ask_vol > 0 else False

    # 수급 변화율
    supply_change_rate = None
    if prev_snapshot and prev_snapshot.total_bid_volume and prev_snapshot.total_bid_volume > 0:
        prev_bid = prev_snapshot.total_bid_volume
        supply_change_rate = (total_bid - prev_bid) / prev_bid * 100

    return OrderbookSignal(
        supply_demand_ratio=round(supply_demand_ratio, 4) if supply_demand_ratio is not None else None,
        spread_ratio=round(spread_ratio, 4) if spread_ratio is not None else None,
        bid1_concentration=round(bid1_concentration, 4) if bid1_concentration is not None else None,
        sell_wall_exists=sell_wall_exists,
        supply_change_rate=round(supply_change_rate, 4) if supply_change_rate is not None else None,
    )


async def _find_closest_snapshot(
    db: AsyncSession,
    stock_code: str,
    target_time: datetime,
) -> OrderbookSnapshot | None:
    """매매 시각과 가장 가까운 스냅샷 조회 (1분 이내)."""
    window_start = target_time - timedelta(minutes=1)
    window_end = target_time + timedelta(minutes=1)

    stmt = (
        select(OrderbookSnapshot)
        .where(
            and_(
                OrderbookSnapshot.stock_code == stock_code,
                OrderbookSnapshot.snapshot_at >= window_start,
                OrderbookSnapshot.snapshot_at <= window_end,
            )
        )
        .order_by(
            sa_func.abs(
                sa_func.extract("epoch", OrderbookSnapshot.snapshot_at)
                - sa_func.extract("epoch", sa_func.cast(target_time, OrderbookSnapshot.snapshot_at.type))
            )
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _find_previous_snapshot(
    db: AsyncSession,
    stock_code: str,
    snapshot_at: datetime,
) -> OrderbookSnapshot | None:
    """직전 스냅샷 조회."""
    stmt = (
        select(OrderbookSnapshot)
        .where(
            and_(
                OrderbookSnapshot.stock_code == stock_code,
                OrderbookSnapshot.snapshot_at < snapshot_at,
            )
        )
        .order_by(OrderbookSnapshot.snapshot_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def analyze_orderbook_effectiveness(
    db: AsyncSession, target_date: date
) -> OrderbookAnalysis:
    """해당일 호가 활용도 검증 분석."""
    start, end = _date_range(target_date)

    # BUY 주문 조회
    buy_stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_placed_at >= start,
                OrderHistory.order_placed_at < end,
                OrderHistory.order_type == "BUY",
            )
        )
        .order_by(OrderHistory.order_placed_at)
    )
    buy_result = await db.execute(buy_stmt)
    buy_orders = buy_result.scalars().all()

    if not buy_orders:
        return OrderbookAnalysis(
            is_sufficient=False,
            message="해당일 BUY 주문이 없습니다.",
            data_count=0,
        )

    # SELL 주문 매칭 (BUY order id -> pnl)
    buy_order_ids = [bo.id for bo in buy_orders]
    sell_stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.buy_order_id.in_(buy_order_ids),
                OrderHistory.order_type == "SELL",
            )
        )
    )
    sell_result = await db.execute(sell_stmt)
    sell_orders = sell_result.scalars().all()
    sell_pnl_map: dict[int, float] = {}
    for so in sell_orders:
        if so.buy_order_id is not None and so.profit_loss_net is not None:
            sell_pnl_map[so.buy_order_id] = float(so.profit_loss_net)

    # 각 BUY 주문 시점의 호가 스냅샷 매칭
    signals: list[OrderbookSignal] = []
    records: list[tuple[OrderbookSignal, float]] = []  # (signal, pnl)

    for bo in buy_orders:
        exec_time = bo.result_executed_at or bo.order_placed_at
        snapshot = await _find_closest_snapshot(db, bo.stock_code, exec_time)
        if not snapshot:
            continue

        prev_snapshot = await _find_previous_snapshot(
            db, bo.stock_code, snapshot.snapshot_at
        )
        signal = _compute_orderbook_signal(snapshot, prev_snapshot)
        signals.append(signal)

        pnl = sell_pnl_map.get(bo.id)
        if pnl is not None:
            records.append((signal, pnl))

    data_count = len(signals)
    is_sufficient = data_count >= 50

    if not records:
        return OrderbookAnalysis(
            is_sufficient=is_sufficient,
            message="데이터 축적 중" if not is_sufficient else None,
            data_count=data_count,
            signals=signals,
        )

    # 수급 우위/열위 시점별 승률 비교
    adv_records = [(s, p) for s, p in records if s.supply_demand_ratio is not None and s.supply_demand_ratio > 1]
    disadv_records = [(s, p) for s, p in records if s.supply_demand_ratio is not None and s.supply_demand_ratio < 1]

    adv_wins = sum(1 for _, p in adv_records if p > 0)
    disadv_wins = sum(1 for _, p in disadv_records if p > 0)

    supply_advantage_win_rate = (
        round(adv_wins / len(adv_records) * 100, 1) if adv_records else None
    )
    supply_disadvantage_win_rate = (
        round(disadv_wins / len(disadv_records) * 100, 1) if disadv_records else None
    )

    # 스프레드 상위 25% 성과 분석
    spread_records = [
        (s, p) for s, p in records if s.spread_ratio is not None
    ]
    wide_spread_avg_pnl = None
    narrow_spread_avg_pnl = None
    if spread_records:
        sorted_by_spread = sorted(
            spread_records, key=lambda x: x[0].spread_ratio or 0, reverse=True
        )
        cutoff = max(1, len(sorted_by_spread) // 4)
        wide = sorted_by_spread[:cutoff]
        narrow = sorted_by_spread[cutoff:]
        wide_spread_avg_pnl = round(
            sum(p for _, p in wide) / len(wide), 2
        ) if wide else None
        narrow_spread_avg_pnl = round(
            sum(p for _, p in narrow) / len(narrow), 2
        ) if narrow else None

    message = None
    if not is_sufficient:
        message = f"데이터 축적 중 ({data_count}건 / 최소 50건)"

    return OrderbookAnalysis(
        supply_advantage_win_rate=supply_advantage_win_rate,
        supply_disadvantage_win_rate=supply_disadvantage_win_rate,
        wide_spread_avg_pnl=wide_spread_avg_pnl,
        narrow_spread_avg_pnl=narrow_spread_avg_pnl,
        is_sufficient=is_sufficient,
        message=message,
        data_count=data_count,
        signals=signals,
    )
