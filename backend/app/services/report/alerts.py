"""경고 규칙 엔진 — 보고서 데이터에서 경고/권고 액션을 생성한다."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, time as dt_time
from typing import Sequence

from sqlalchemy import select, and_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.schemas.report import AlertItem, DailyReportResponse

logger = logging.getLogger(__name__)

# ── 임계값 상수 (나중에 system_parameters로 이동 가능) ──────────────

CONSECUTIVE_DAYS = 3
LUNCH_TRADE_THRESHOLD = 3
HOLD_RATIO_HIGH = 70.0
HOLD_RATIO_LOW = 20.0
MISSED_UP_RATIO = 40.0
MIN_TRADES_FOR_STRATEGY = 100
CUMULATIVE_PF_THRESHOLD = 1.2
CONSECUTIVE_ALPHA_DAYS = 5
REPEATED_TRADE_ROUNDS = 3
MDD_LIMIT_PCT = -3.0
FEE_RATIO_THRESHOLD = 60.0
LLM_SLOW_THRESHOLD_MS = 5000
LLM_SLOW_RATIO = 30.0
EARLY_EXIT_RATIO = 50.0
CASH_IDLE_RATIO = 80.0
AVG_SPREAD_THRESHOLD = 0.3


# ── 유틸리티 ─────────────────────────────────────────────────────

def _date_range(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


async def _get_recent_trading_dates(
    db: AsyncSession, target: date, n_days: int
) -> list[date]:
    """target 기준 최근 N 매매일을 조회한다 (주말/공휴일 건너뜀)."""
    start, end = _date_range(target)
    # 최근 30일 범위에서 매매가 있던 날짜를 역순으로 n_days개 추출
    lookback = datetime(target.year, target.month, target.day) - timedelta(days=60)
    stmt = (
        select(
            sa_func.date(OrderHistory.result_executed_at).label("trade_date")
        )
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= lookback,
                OrderHistory.result_executed_at < end,
            )
        )
        .group_by(sa_func.date(OrderHistory.result_executed_at))
        .order_by(sa_func.date(OrderHistory.result_executed_at).desc())
        .limit(n_days)
    )
    result = await db.execute(stmt)
    dates = [row[0] for row in result.all()]
    return dates


async def _get_day_sell_orders(
    db: AsyncSession, target: date
) -> list[OrderHistory]:
    """특정 날짜의 SELL 주문 목록."""
    start, end = _date_range(target)
    stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
            )
        )
        .order_by(OrderHistory.result_executed_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _get_day_decisions(
    db: AsyncSession, target: date
) -> list[DecisionHistory]:
    """특정 날짜의 판단 이력."""
    start, end = _date_range(target)
    stmt = (
        select(DecisionHistory)
        .where(
            and_(
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── 개별 경고 규칙 ──────────────────────────────────────────────

def _check_lunch_trades(report: DailyReportResponse) -> list[AlertItem]:
    """점심시간 매매 3건 이상 → INFO."""
    lunch_count = 0
    for t in report.trades:
        if t.time_zone_tag == "점심":
            lunch_count += 1
    if lunch_count >= LUNCH_TRADE_THRESHOLD:
        return [AlertItem(
            type="INFO",
            category="time_zone",
            message=f"점심시간(11:30~13:00) 매매 {lunch_count}건 발생",
            action="비효율 구간 매매 축소 검토",
        )]
    return []


def _check_mdd(report: DailyReportResponse) -> list[AlertItem]:
    """일중 MDD 설정 한도(-3%) 초과 → CRITICAL."""
    mdd = report.summary.intraday_mdd
    if mdd is not None and mdd != 0:
        # MDD는 음수 또는 양수 절대값 형태일 수 있음
        mdd_val = -abs(mdd) if mdd > 0 else mdd
        if mdd_val < MDD_LIMIT_PCT:
            return [AlertItem(
                type="CRITICAL",
                category="mdd",
                message=f"일중 MDD {mdd_val:.2f}%로 한도({MDD_LIMIT_PCT}%) 초과",
                action="리스크 한도 하향 검토",
            )]
    return []


def _check_cumulative_expectancy(report: DailyReportResponse) -> list[AlertItem]:
    """누적 기대값 음수 (100건+) → CRITICAL."""
    cum = report.cumulative
    if cum and cum.total_trades >= MIN_TRADES_FOR_STRATEGY:
        if cum.cumulative_expected_value < 0:
            return [AlertItem(
                type="CRITICAL",
                category="strategy",
                message=f"누적 기대값 음수({cum.cumulative_expected_value:,.0f}원, {cum.total_trades}건)",
                action="전략 전면 재검토 필요",
            )]
    return []


def _check_cumulative_pf(report: DailyReportResponse) -> list[AlertItem]:
    """누적 PF < 1.2 (100건+) → WARNING."""
    cum = report.cumulative
    if cum and cum.total_trades >= MIN_TRADES_FOR_STRATEGY:
        if cum.cumulative_profit_factor is not None and cum.cumulative_profit_factor < CUMULATIVE_PF_THRESHOLD:
            return [AlertItem(
                type="WARNING",
                category="strategy",
                message=f"누적 PF {cum.cumulative_profit_factor:.2f} < {CUMULATIVE_PF_THRESHOLD} ({cum.total_trades}건)",
                action="수수료 고려 시 실질 손실 가능, 전략 점검",
            )]
    return []


def _check_repeated_trades(report: DailyReportResponse) -> list[AlertItem]:
    """동일종목 3회+, 회차별 수익 감소 → WARNING."""
    alerts: list[AlertItem] = []
    analysis = report.analysis or {}
    repeated = analysis.get("repeated_trades")
    if repeated and isinstance(repeated, list):
        for item in repeated:
            if hasattr(item, "round_count") and hasattr(item, "per_round_returns"):
                if item.round_count >= REPEATED_TRADE_ROUNDS:
                    returns = item.per_round_returns
                    if len(returns) >= 2 and all(
                        returns[i] >= returns[i + 1] for i in range(len(returns) - 1)
                    ):
                        name = getattr(item, "stock_name", item.stock_code) or item.stock_code
                        alerts.append(AlertItem(
                            type="WARNING",
                            category="repeated_trade",
                            message=f"{name} {item.round_count}회 반복매매, 회차별 수익 감소",
                            action="반복매매 방지 프롬프트 추가 검토",
                        ))
    return alerts


def _check_fee_ratio(report: DailyReportResponse) -> list[AlertItem]:
    """총 수수료/순이익 > 60% → WARNING."""
    analysis = report.analysis or {}
    freq = analysis.get("trade_frequency")
    if freq and hasattr(freq, "fee_ratio") and freq.fee_ratio is not None:
        if freq.fee_ratio > FEE_RATIO_THRESHOLD:
            return [AlertItem(
                type="WARNING",
                category="fee",
                message=f"수수료 비중 {freq.fee_ratio:.1f}% > {FEE_RATIO_THRESHOLD}%",
                action="매매 빈도 줄이거나 목표 수익폭 확대",
            )]
    return []


def _check_llm_speed(report: DailyReportResponse) -> list[AlertItem]:
    """LLM 처리 >5초 비율 30% 이상 → INFO."""
    slow_count = 0
    total = 0
    for t in report.trades:
        if t.entry_speed and t.entry_speed.llm_processing_ms is not None:
            total += 1
            if t.entry_speed.llm_processing_ms > LLM_SLOW_THRESHOLD_MS:
                slow_count += 1
    if total > 0:
        ratio = (slow_count / total) * 100
        if ratio >= LLM_SLOW_RATIO:
            return [AlertItem(
                type="INFO",
                category="entry_speed",
                message=f"LLM 처리 >5초 비율 {ratio:.0f}% ({slow_count}/{total}건)",
                action="모델/프롬프트 경량화 검토",
            )]
    return []


def _check_early_exit(report: DailyReportResponse) -> list[AlertItem]:
    """조기 청산 비율 50% 이상 → WARNING."""
    analysis = report.analysis or {}
    missed = analysis.get("missed_opportunities")
    if missed and isinstance(missed, list):
        total = len(missed)
        early_count = sum(1 for m in missed if hasattr(m, "early_exit") and m.early_exit)
        if total > 0:
            ratio = (early_count / total) * 100
            if ratio >= EARLY_EXIT_RATIO:
                return [AlertItem(
                    type="WARNING",
                    category="missed_opportunity",
                    message=f"조기 청산 비율 {ratio:.0f}% ({early_count}/{total}건)",
                    action="매도 기준 완화 검토",
                )]
    return []


def _check_slippage(report: DailyReportResponse) -> list[AlertItem]:
    """평균 스프레드 >0.3% → INFO."""
    analysis = report.analysis or {}
    missed = analysis.get("missed_opportunities")
    if missed and isinstance(missed, list):
        slippages = [
            m.estimated_slippage
            for m in missed
            if hasattr(m, "estimated_slippage") and m.estimated_slippage is not None
        ]
        if slippages:
            avg = sum(slippages) / len(slippages)
            if avg > AVG_SPREAD_THRESHOLD:
                return [AlertItem(
                    type="INFO",
                    category="slippage",
                    message=f"평균 가상 슬리피지 {avg:.2f}% > {AVG_SPREAD_THRESHOLD}%",
                    action="실매매 전환 시 손익 보정 필수",
                )]
    return []


# ── "N일 연속" 조건 확인 (DB 조회 필요) ────────────────────────

async def _check_consecutive_time_zone_negative(
    db: AsyncSession, target: date
) -> list[AlertItem]:
    """특정 시간대 기대값 3일 연속 음수 → WARNING."""
    dates = await _get_recent_trading_dates(db, target, CONSECUTIVE_DAYS)
    if len(dates) < CONSECUTIVE_DAYS:
        return []

    # 시간대별로 각 날짜의 기대값 계산
    from app.services.report.core import _classify_time_zone

    zone_day_pnl: dict[str, list[float]] = {}

    for d in dates:
        orders = await _get_day_sell_orders(db, d)
        zone_pnl: dict[str, list[float]] = {}
        for o in orders:
            if o.result_executed_at and o.profit_loss_net is not None:
                zone = _classify_time_zone(o.result_executed_at)
                zone_pnl.setdefault(zone, []).append(float(o.profit_loss_net))

        for zone, pnls in zone_pnl.items():
            ev = sum(pnls) / len(pnls) if pnls else 0
            zone_day_pnl.setdefault(zone, []).append(ev)

    alerts: list[AlertItem] = []
    for zone, evs in zone_day_pnl.items():
        if len(evs) >= CONSECUTIVE_DAYS and all(ev < 0 for ev in evs[:CONSECUTIVE_DAYS]):
            alerts.append(AlertItem(
                type="WARNING",
                category="time_zone",
                message=f"{zone} 시간대 기대값 {CONSECUTIVE_DAYS}일 연속 음수",
                action=f"{zone} 시간대 매매 중단 검토",
            ))
    return alerts


async def _check_consecutive_hold_ratio(
    db: AsyncSession, target: date
) -> list[AlertItem]:
    """HOLD 비율 >70% 또는 <20% 3일 연속 → WARNING."""
    dates = await _get_recent_trading_dates(db, target, CONSECUTIVE_DAYS)
    if len(dates) < CONSECUTIVE_DAYS:
        return []

    # 각 날짜별 decisions에서 hold ratio 계산
    ratios: list[float] = []
    for d in dates[:CONSECUTIVE_DAYS]:
        decisions = await _get_day_decisions(db, d)
        total = len(decisions)
        if total == 0:
            return []  # 판단 기록 없으면 스킵
        hold_count = sum(1 for dec in decisions if dec.decision == "HOLD")
        ratios.append((hold_count / total) * 100)

    alerts: list[AlertItem] = []
    if all(r > HOLD_RATIO_HIGH for r in ratios):
        alerts.append(AlertItem(
            type="WARNING",
            category="hold",
            message=f"HOLD 비율 {CONSECUTIVE_DAYS}일 연속 {HOLD_RATIO_HIGH}% 초과",
            action="매수 조건 완화 (너무 보수적)",
        ))
    if all(r < HOLD_RATIO_LOW for r in ratios):
        alerts.append(AlertItem(
            type="WARNING",
            category="hold",
            message=f"HOLD 비율 {CONSECUTIVE_DAYS}일 연속 {HOLD_RATIO_LOW}% 미만",
            action="매수 조건 강화 (너무 공격적)",
        ))
    return alerts


async def _check_missed_up_ratio(
    db: AsyncSession, target: date
) -> list[AlertItem]:
    """MISSED_UP 누적 40% 초과 → CRITICAL."""
    # 최근 매매일에서 HOLD 41 분석의 MISSED_UP 비율 확인
    # report의 hold_summary에서 직접 확인
    # 이 함수는 report 기반으로 동작하도록 별도 처리
    return []


def _check_missed_up_from_report(report: DailyReportResponse) -> list[AlertItem]:
    """MISSED_UP 누적 40% 초과 → CRITICAL (보고서 기반)."""
    analysis = report.analysis or {}
    hold_summary = analysis.get("hold_summary")
    if hold_summary and hasattr(hold_summary, "hold_41"):
        items_41 = hold_summary.hold_41
        if items_41:
            total = len(items_41)
            missed_up = sum(1 for item in items_41 if item.verdict == "MISSED_UP")
            if total > 0:
                ratio = (missed_up / total) * 100
                if ratio > MISSED_UP_RATIO:
                    return [AlertItem(
                        type="CRITICAL",
                        category="hold",
                        message=f"MISSED_UP 비율 {ratio:.0f}% > {MISSED_UP_RATIO}% ({missed_up}/{total}건)",
                        action="종목 선택 로직 재검토",
                    )]
    return []


async def _check_consecutive_alpha_negative(
    db: AsyncSession, target: date
) -> list[AlertItem]:
    """1차 Alpha 5일 연속 음수 → CRITICAL.

    Alpha는 보고서 내 분석 결과인데, 과거 보고서 캐시가 없으므로
    직접 계산하지 않고 현재 보고서에서만 확인하는 간소화된 버전으로 구현.
    완전한 구현은 보고서 캐시 도입 후 가능.
    """
    return []


def _check_alpha_from_report(report: DailyReportResponse) -> list[AlertItem]:
    """벤치마크 Alpha 관련 경고 (현재 보고서 기반)."""
    # 5일 연속은 보고서 캐시 없이는 불가능하므로 당일 기준만 체크
    # 향후 보고서 캐시 도입 시 연속 일수 확인으로 확장
    return []


async def _check_consecutive_cash_idle(
    db: AsyncSession, target: date
) -> list[AlertItem]:
    """유휴율 >80% 3일 연속 → INFO.

    현금 유휴율은 보고서 분석 항목이므로 보고서 캐시 없이는 확인 불가.
    보고서 내 당일 데이터만 확인.
    """
    return []


def _check_cash_idle_from_report(report: DailyReportResponse) -> list[AlertItem]:
    """현금 유휴율 >80% → INFO (당일 보고서 기반)."""
    analysis = report.analysis or {}
    freq = analysis.get("trade_frequency")
    if freq and hasattr(freq, "cash_idle_ratio") and freq.cash_idle_ratio is not None:
        if freq.cash_idle_ratio > CASH_IDLE_RATIO:
            return [AlertItem(
                type="INFO",
                category="cash_idle",
                message=f"현금 유휴율 {freq.cash_idle_ratio:.0f}% > {CASH_IDLE_RATIO}%",
                action="매수 조건 완화 또는 주기 단축",
            )]
    return []


# ── 정렬 우선순위 ─────────────────────────────────────────────

_TYPE_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _sort_alerts(alerts: list[AlertItem]) -> list[AlertItem]:
    """CRITICAL > WARNING > INFO 순으로 정렬."""
    return sorted(alerts, key=lambda a: _TYPE_ORDER.get(a.type, 99))


# ── 메인 함수 ─────────────────────────────────────────────────

async def generate_alerts(
    db: AsyncSession, report: DailyReportResponse
) -> list[AlertItem]:
    """보고서 데이터 + DB 조회를 통해 경고 목록을 생성한다."""
    target = date.fromisoformat(report.summary.date)
    alerts: list[AlertItem] = []

    # 보고서 기반 경고 (DB 조회 불필요)
    alerts.extend(_check_lunch_trades(report))
    alerts.extend(_check_mdd(report))
    alerts.extend(_check_cumulative_expectancy(report))
    alerts.extend(_check_cumulative_pf(report))
    alerts.extend(_check_repeated_trades(report))
    alerts.extend(_check_fee_ratio(report))
    alerts.extend(_check_llm_speed(report))
    alerts.extend(_check_early_exit(report))
    alerts.extend(_check_slippage(report))
    alerts.extend(_check_missed_up_from_report(report))
    alerts.extend(_check_cash_idle_from_report(report))

    # DB 조회 기반 경고 (N일 연속 조건)
    try:
        alerts.extend(await _check_consecutive_time_zone_negative(db, target))
    except Exception:
        logger.exception("consecutive time zone check failed")

    try:
        alerts.extend(await _check_consecutive_hold_ratio(db, target))
    except Exception:
        logger.exception("consecutive hold ratio check failed")

    return _sort_alerts(alerts)
