"""이벤트 트레이더 성과 분석 및 Go/No-Go 게이트 서비스."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.system_parameter import SystemParameter
from app.models.trading_event import TradingEvent
from app.services.param_helper import get_param

logger = logging.getLogger(__name__)


# ── 데이터 클래스 ─────────────────────────────────────────────────────


@dataclass
class EventTypeMetrics:
    event_type: str
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_profit_rate: float
    profit_factor: float


@dataclass
class ConfidenceBucketMetrics:
    bucket: str
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_profit_rate: float


@dataclass
class PerformanceMetrics:
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float  # 총 이익 / 총 손실
    kelly_pct: float
    avg_profit_rate: float
    avg_loss_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    by_event_type: dict[str, EventTypeMetrics] = field(default_factory=dict)
    by_confidence_bucket: dict[str, ConfidenceBucketMetrics] = field(default_factory=dict)


@dataclass
class GateResult:
    gate_level: str  # "20", "50", "100"
    passed: bool
    details: dict
    recommendation: str  # "continue", "stop", "review"


# ── 성과 분석 ─────────────────────────────────────────────────────────


async def _get_sell_orders(
    db: AsyncSession,
    strategy_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[OrderHistory]:
    """전략의 SELL 주문 목록 조회."""
    conditions = [
        OrderHistory.strategy_id == strategy_id,
        OrderHistory.order_type == "SELL",
    ]
    if start_date:
        conditions.append(OrderHistory.created_at >= start_date)
    if end_date:
        from datetime import datetime, timedelta
        end_dt = datetime.combine(end_date, datetime.max.time())
        conditions.append(OrderHistory.created_at <= end_dt)

    result = await db.execute(
        select(OrderHistory)
        .where(and_(*conditions))
        .order_by(OrderHistory.created_at.asc())
    )
    return list(result.scalars().all())


def _compute_base_metrics(orders: list[OrderHistory]) -> dict:
    """SELL 주문 목록에서 기본 성과 지표를 계산한다."""
    total = len(orders)
    if total == 0:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "kelly_pct": 0.0,
            "avg_profit_rate": 0.0,
            "avg_loss_rate": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": None,
        }

    wins = []
    losses = []
    profit_rates = []

    for o in orders:
        pl = float(o.profit_loss or 0)
        pr = float(o.profit_rate or 0)
        profit_rates.append(pr)
        if pl > 0:
            wins.append(o)
        elif pl < 0:
            losses.append(o)

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total if total > 0 else 0.0

    total_profit = sum(float(o.profit_loss or 0) for o in wins)
    total_loss_abs = abs(sum(float(o.profit_loss or 0) for o in losses))
    profit_factor = total_profit / total_loss_abs if total_loss_abs > 0 else float("inf") if total_profit > 0 else 0.0

    avg_profit_rate = (
        sum(float(o.profit_rate or 0) for o in wins) / win_count
        if win_count > 0 else 0.0
    )
    avg_loss_rate = (
        sum(float(o.profit_rate or 0) for o in losses) / loss_count
        if loss_count > 0 else 0.0
    )

    # Kelly %: W - (1 - W) / (avg_win / avg_loss)
    kelly_pct = 0.0
    if win_count > 0 and loss_count > 0 and avg_loss_rate != 0:
        avg_win_abs = abs(avg_profit_rate)
        avg_loss_abs = abs(avg_loss_rate)
        if avg_loss_abs > 0:
            kelly_pct = win_rate - (1 - win_rate) / (avg_win_abs / avg_loss_abs)

    # Max drawdown: 누적 손익 기준
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for o in orders:
        cumulative += float(o.profit_loss_net or o.profit_loss or 0)
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    # drawdown %: peak 대비
    max_drawdown_pct = (max_dd / peak * 100) if peak > 0 else 0.0

    # Sharpe ratio: 수익률 평균 / 표준편차
    sharpe_ratio = None
    if len(profit_rates) >= 2:
        mean_r = sum(profit_rates) / len(profit_rates)
        variance = sum((r - mean_r) ** 2 for r in profit_rates) / (len(profit_rates) - 1)
        std_r = math.sqrt(variance)
        if std_r > 0:
            sharpe_ratio = mean_r / std_r

    return {
        "total_trades": total,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "kelly_pct": round(kelly_pct, 4),
        "avg_profit_rate": round(avg_profit_rate, 4),
        "avg_loss_rate": round(avg_loss_rate, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
    }


async def calculate_performance(
    db: AsyncSession,
    strategy_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PerformanceMetrics:
    """전략의 전체 성과 지표를 계산한다."""
    orders = await _get_sell_orders(db, strategy_id, start_date, end_date)
    base = _compute_base_metrics(orders)

    # 이벤트 유형별 성과
    by_event_type = await _calculate_by_event_type(db, strategy_id, orders)

    # Confidence 구간별 성과
    by_confidence = await _calculate_by_confidence_bucket(db, strategy_id, orders)

    return PerformanceMetrics(
        **base,
        by_event_type=by_event_type,
        by_confidence_bucket=by_confidence,
    )


# ── 이벤트 유형별 성과 ───────────────────────────────────────────────


async def _calculate_by_event_type(
    db: AsyncSession,
    strategy_id: int,
    orders: list[OrderHistory],
) -> dict[str, EventTypeMetrics]:
    """이벤트 유형별 성과를 계산한다."""
    if not orders:
        return {}

    # event_id가 있는 주문만 대상
    event_ids = [o.event_id for o in orders if o.event_id is not None]
    if not event_ids:
        return {}

    # 이벤트 유형 맵 조회
    result = await db.execute(
        select(TradingEvent.id, TradingEvent.event_type)
        .where(TradingEvent.id.in_(event_ids))
    )
    event_type_map = {row.id: row.event_type for row in result.all()}

    # 유형별 그룹핑
    grouped: dict[str, list[OrderHistory]] = {}
    for o in orders:
        if o.event_id and o.event_id in event_type_map:
            et = event_type_map[o.event_id]
            grouped.setdefault(et, []).append(o)

    metrics = {}
    for et, group_orders in grouped.items():
        base = _compute_base_metrics(group_orders)
        metrics[et] = EventTypeMetrics(
            event_type=et,
            total_trades=base["total_trades"],
            win_count=base["win_count"],
            loss_count=base["loss_count"],
            win_rate=base["win_rate"],
            avg_profit_rate=base["avg_profit_rate"],
            profit_factor=base["profit_factor"],
        )
    return metrics


# ── Confidence 구간별 성과 ────────────────────────────────────────────

CONFIDENCE_BUCKETS = [
    ("0.0-0.3", 0.0, 0.3),
    ("0.3-0.5", 0.3, 0.5),
    ("0.5-0.7", 0.5, 0.7),
    ("0.7-1.0", 0.7, 1.0),
]


async def _calculate_by_confidence_bucket(
    db: AsyncSession,
    strategy_id: int,
    orders: list[OrderHistory],
) -> dict[str, ConfidenceBucketMetrics]:
    """Confidence 구간별 성과를 계산한다."""
    if not orders:
        return {}

    # decision_history_id로 confidence 조회
    dh_ids = [o.decision_history_id for o in orders if o.decision_history_id is not None]
    if not dh_ids:
        return {}

    result = await db.execute(
        select(DecisionHistory.id, DecisionHistory.parsed_decision)
        .where(DecisionHistory.id.in_(dh_ids))
    )
    confidence_map: dict[int, float] = {}
    for row in result.all():
        parsed = row.parsed_decision
        if parsed and isinstance(parsed, dict) and "confidence" in parsed:
            try:
                confidence_map[row.id] = float(parsed["confidence"])
            except (ValueError, TypeError):
                pass

    # 구간별 그룹핑
    grouped: dict[str, list[OrderHistory]] = {b[0]: [] for b in CONFIDENCE_BUCKETS}
    for o in orders:
        if o.decision_history_id in confidence_map:
            conf = confidence_map[o.decision_history_id]
            for bucket_name, low, high in CONFIDENCE_BUCKETS:
                if low <= conf < high or (high == 1.0 and conf == 1.0):
                    grouped[bucket_name].append(o)
                    break

    metrics = {}
    for bucket_name, bucket_orders in grouped.items():
        if not bucket_orders:
            continue
        base = _compute_base_metrics(bucket_orders)
        metrics[bucket_name] = ConfidenceBucketMetrics(
            bucket=bucket_name,
            total_trades=base["total_trades"],
            win_count=base["win_count"],
            loss_count=base["loss_count"],
            win_rate=base["win_rate"],
            avg_profit_rate=base["avg_profit_rate"],
        )
    return metrics


# ── Go/No-Go 게이트 ──────────────────────────────────────────────────


async def _set_param(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(
        select(SystemParameter).where(
            SystemParameter.key == key,
            SystemParameter.strategy_id.is_(None),
        )
    )
    param = result.scalar_one_or_none()
    if param:
        param.value = value
    else:
        db.add(SystemParameter(key=key, value=value))
    await db.flush()


async def check_go_no_go_gate(
    db: AsyncSession,
    strategy_id: int,
) -> GateResult | None:
    """현재 거래 건수에 따라 적절한 게이트 체크를 실행한다.

    Returns None if no gate level has been reached yet.
    """
    orders = await _get_sell_orders(db, strategy_id)
    total = len(orders)

    if total < 20:
        return None

    base = _compute_base_metrics(orders)

    # ── 20건 게이트 ──
    if 20 <= total < 50:
        pf = base["profit_factor"]
        wr = base["win_rate"]
        passed = not (pf < 0.5 or wr < 0.15)
        return GateResult(
            gate_level="20",
            passed=passed,
            details={
                "total_trades": total,
                "profit_factor": pf,
                "win_rate": wr,
                "threshold_pf": 0.5,
                "threshold_win_rate": 0.15,
            },
            recommendation="continue" if passed else "stop",
        )

    # ── 50건 게이트 ──
    if 50 <= total < 100:
        pf = base["profit_factor"]
        wr = base["win_rate"]
        kelly = base["kelly_pct"]
        passed = pf >= 1.2 and wr >= 0.38 and kelly >= 0.05

        # 실패 횟수 추적
        fail_count = int(await get_param(db, "gate_50_fail_count", "0"))
        if not passed:
            fail_count += 1
            await _set_param(db, "gate_50_fail_count", str(fail_count))
            await db.commit()

        recommendation = "continue" if passed else ("stop" if fail_count > 2 else "review")

        return GateResult(
            gate_level="50",
            passed=passed,
            details={
                "total_trades": total,
                "profit_factor": pf,
                "win_rate": wr,
                "kelly_pct": kelly,
                "threshold_pf": 1.2,
                "threshold_win_rate": 0.38,
                "threshold_kelly": 0.05,
                "fail_count": fail_count,
            },
            recommendation=recommendation,
        )

    # ── 100건 게이트 ──
    if total >= 100:
        first_half = orders[:total // 2]
        second_half = orders[total // 2:]
        first_metrics = _compute_base_metrics(first_half)
        second_metrics = _compute_base_metrics(second_half)

        first_wr = first_metrics["win_rate"]
        second_wr = second_metrics["win_rate"]

        # 괴리율: |전반 - 후반| / max(전반, 후반)
        max_wr = max(first_wr, second_wr)
        divergence = abs(first_wr - second_wr) / max_wr if max_wr > 0 else 0.0
        passed = divergence < 0.30

        return GateResult(
            gate_level="100",
            passed=passed,
            details={
                "total_trades": total,
                "first_half_win_rate": first_wr,
                "second_half_win_rate": second_wr,
                "divergence": round(divergence, 4),
                "threshold_divergence": 0.30,
                "first_half_pf": first_metrics["profit_factor"],
                "second_half_pf": second_metrics["profit_factor"],
            },
            recommendation="continue" if passed else "review",
        )

    return None
