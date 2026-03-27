"""누적 추적 지표 + 전략 버전 관리."""

from __future__ import annotations

import math
from datetime import date, datetime
from collections import defaultdict

from sqlalchemy import select, and_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.schemas.report import (
    CumulativeStats,
    RollingStats,
    RollingWindowStats,
    VersionComparison,
)


def _confidence_label(n: int) -> str:
    """누적 거래 수에 따른 신뢰도 라벨."""
    if n < 30:
        return "데이터 부족 — 참고만"
    elif n < 50:
        return "초기 추세 — 판단 보류"
    elif n < 100:
        return "추세 확인 중"
    else:
        return "통계적 판단 가능"


def _compute_stats_from_pnl(
    pnl_list: list[float],
) -> tuple[float, float, float | None]:
    """손익 리스트로부터 (승률%, 기대값, PF)를 반환."""
    if not pnl_list:
        return 0.0, 0.0, None

    total = len(pnl_list)
    profits = [p for p in pnl_list if p >= 0]
    losses = [p for p in pnl_list if p < 0]

    win_count = len(profits)
    loss_count = len(losses)
    win_rate = (win_count / total) * 100

    avg_profit = sum(profits) / win_count if win_count > 0 else 0.0
    avg_loss = sum(losses) / loss_count if loss_count > 0 else 0.0

    loss_rate = (loss_count / total) * 100
    expected_value = (win_rate / 100 * avg_profit) - (loss_rate / 100 * abs(avg_loss))

    total_profit = sum(profits)
    total_loss = abs(sum(losses))
    pf: float | None = None
    if total_loss > 0:
        pf = total_profit / total_loss
    elif total_profit > 0:
        pf = float("inf")

    return win_rate, expected_value, pf


def _compute_cumulative_mdd(daily_pnl: list[float]) -> float | None:
    """일별 손익 시계열로부터 누적 MDD 계산."""
    if not daily_pnl:
        return None

    cumulative = 0.0
    peak = 0.0
    mdd = 0.0

    for pnl in daily_pnl:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > mdd:
            mdd = drawdown

    return mdd


async def _get_active_strategy_version(db: AsyncSession) -> tuple[str, datetime | None]:
    """현재 활성 전략 버전과 해당 버전의 활성화 시점을 반환.

    Returns:
        (version_string, version_start_datetime)
    """
    # buy/sell 프롬프트의 활성 버전 조회
    stmt = (
        select(PromptTemplate.prompt_type, PromptTemplate.version, PromptTemplate.created_at)
        .where(PromptTemplate.is_active.is_(True))
        .where(PromptTemplate.prompt_type.in_(["buy", "sell"]))
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return "v0.0", None

    buy_version = 0
    sell_version = 0
    latest_created = None

    for prompt_type, version, created_at in rows:
        if prompt_type == "buy":
            buy_version = version
        elif prompt_type == "sell":
            sell_version = version
        if latest_created is None or created_at > latest_created:
            latest_created = created_at

    version_str = f"v{buy_version}.{sell_version}"
    return version_str, latest_created


async def _get_sell_pnl_since(
    db: AsyncSession,
    since: datetime | None,
    until: datetime | None = None,
) -> list[float]:
    """지정 기간 내 SELL 주문의 세후 손익 리스트 반환."""
    conditions = [
        OrderHistory.order_type == "SELL",
        OrderHistory.profit_loss_net.is_not(None),
    ]
    if since is not None:
        conditions.append(OrderHistory.result_executed_at >= since)
    if until is not None:
        conditions.append(OrderHistory.result_executed_at < until)

    stmt = (
        select(OrderHistory.profit_loss_net)
        .where(and_(*conditions))
        .order_by(OrderHistory.result_executed_at.asc())
    )
    result = await db.execute(stmt)
    return [float(row[0]) for row in result.all()]


async def _get_daily_pnl_since(
    db: AsyncSession,
    since: datetime | None,
    until: datetime | None = None,
) -> list[float]:
    """지정 기간 내 일별 합산 손익 리스트 반환."""
    conditions = [
        OrderHistory.order_type == "SELL",
        OrderHistory.profit_loss_net.is_not(None),
    ]
    if since is not None:
        conditions.append(OrderHistory.result_executed_at >= since)
    if until is not None:
        conditions.append(OrderHistory.result_executed_at < until)

    stmt = (
        select(
            sa_func.date(OrderHistory.result_executed_at).label("trade_date"),
            sa_func.sum(OrderHistory.profit_loss_net).label("daily_pnl"),
        )
        .where(and_(*conditions))
        .group_by(sa_func.date(OrderHistory.result_executed_at))
        .order_by(sa_func.date(OrderHistory.result_executed_at).asc())
    )
    result = await db.execute(stmt)
    return [float(row[1]) for row in result.all()]


async def get_cumulative_stats(
    db: AsyncSession, target_date: date
) -> CumulativeStats:
    """누적 지표 계산."""
    # 1. 현재 전략 버전 식별
    version_str, version_start = await _get_active_strategy_version(db)

    # 2. 버전 내 누적 데이터 (until = target_date 다음날)
    until = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)
    version_pnl = await _get_sell_pnl_since(db, version_start, until)
    version_trade_count = len(version_pnl)

    # 3. 전체 누적 데이터
    all_pnl = await _get_sell_pnl_since(db, None, until)
    total_trades = len(all_pnl)

    if total_trades == 0:
        return CumulativeStats(
            strategy_version=version_str,
            confidence_label=_confidence_label(0),
        )

    # 4. 누적 지표 계산
    win_rate, expected_value, pf = _compute_stats_from_pnl(all_pnl)

    # 5. 누적 MDD (일별 기준)
    daily_pnl = await _get_daily_pnl_since(db, None, until)
    cumulative_mdd = _compute_cumulative_mdd(daily_pnl)

    # 6. 95% 신뢰구간
    p = win_rate / 100
    n = total_trades
    ci_lower: float | None = None
    ci_upper: float | None = None
    if n > 0:
        margin = 1.96 * math.sqrt(p * (1 - p) / n)
        ci_lower = max(0.0, (p - margin) * 100)
        ci_upper = min(100.0, (p + margin) * 100)

    return CumulativeStats(
        cumulative_win_rate=win_rate,
        cumulative_expected_value=expected_value,
        cumulative_profit_factor=pf,
        cumulative_mdd=cumulative_mdd,
        total_trades=total_trades,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        strategy_version=version_str,
        version_trade_count=version_trade_count,
        confidence_label=_confidence_label(total_trades),
    )


async def get_rolling_stats(
    db: AsyncSession, target_date: date
) -> RollingStats:
    """최근 N건 롤링 윈도우 통계."""
    until = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)

    # 최근 100건 조회 (최대 윈도우)
    stmt = (
        select(OrderHistory.profit_loss_net)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.profit_loss_net.is_not(None),
                OrderHistory.result_executed_at <= until,
            )
        )
        .order_by(OrderHistory.result_executed_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    recent_pnl = [float(row[0]) for row in result.all()]
    # 역순으로 되어 있으므로 다시 뒤집기 (시간 순)
    recent_pnl.reverse()

    windows: list[RollingWindowStats] = []
    for window_size in [30, 50, 100]:
        if len(recent_pnl) < window_size:
            windows.append(RollingWindowStats(
                window_size=window_size,
                win_rate=None,
                expected_value=None,
            ))
        else:
            window_data = recent_pnl[-window_size:]
            win_rate, ev, _ = _compute_stats_from_pnl(window_data)
            windows.append(RollingWindowStats(
                window_size=window_size,
                win_rate=win_rate,
                expected_value=ev,
            ))

    return RollingStats(windows=windows)


async def get_version_comparison(
    db: AsyncSession,
) -> list[VersionComparison]:
    """전략 버전별 성과 비교."""
    # 모든 프롬프트 버전 조회
    stmt = (
        select(
            PromptTemplate.prompt_type,
            PromptTemplate.version,
            PromptTemplate.created_at,
        )
        .where(PromptTemplate.prompt_type.in_(["buy", "sell"]))
        .order_by(PromptTemplate.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return []

    # 버전별 기간 구성
    # buy/sell 각각의 버전 이력 추적
    buy_versions: list[tuple[int, datetime]] = []
    sell_versions: list[tuple[int, datetime]] = []

    for prompt_type, version, created_at in rows:
        if prompt_type == "buy":
            buy_versions.append((version, created_at))
        else:
            sell_versions.append((version, created_at))

    if not buy_versions:
        buy_versions = [(0, datetime.min)]
    if not sell_versions:
        sell_versions = [(0, datetime.min)]

    # 모든 변경 시점을 모아서 시간순 정렬
    # 각 시점에서의 buy_ver, sell_ver 조합으로 버전 구성
    events: list[tuple[datetime, str, int]] = []
    for ver, created in buy_versions:
        events.append((created, "buy", ver))
    for ver, created in sell_versions:
        events.append((created, "sell", ver))
    events.sort(key=lambda x: x[0])

    # 시간순으로 버전 조합 생성
    current_buy = buy_versions[0][0]
    current_sell = sell_versions[0][0]
    version_periods: list[tuple[str, datetime, datetime | None]] = []

    for evt_time, evt_type, evt_ver in events:
        if evt_type == "buy":
            current_buy = evt_ver
        else:
            current_sell = evt_ver

        ver_str = f"v{current_buy}.{current_sell}"
        if version_periods and version_periods[-1][0] == ver_str:
            continue  # 같은 버전이면 스킵

        # 이전 버전의 종료 시점 설정
        if version_periods:
            prev_ver, prev_start, _ = version_periods[-1]
            version_periods[-1] = (prev_ver, prev_start, evt_time)

        version_periods.append((ver_str, evt_time, None))

    # 각 버전 기간별 성과 계산
    comparisons: list[VersionComparison] = []
    for ver_str, start, end in version_periods:
        pnl_list = await _get_sell_pnl_since(db, start, end)
        if not pnl_list:
            comparisons.append(VersionComparison(
                version=ver_str,
                trade_count=0,
            ))
            continue

        win_rate, ev, pf = _compute_stats_from_pnl(pnl_list)
        comparisons.append(VersionComparison(
            version=ver_str,
            win_rate=win_rate,
            expected_value=ev,
            profit_factor=pf,
            trade_count=len(pnl_list),
        ))

    return comparisons
