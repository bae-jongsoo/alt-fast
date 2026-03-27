"""보고서 서비스 패키지."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.report import DailyReportResponse
from app.services.report.core import (
    get_daily_summary,
    get_trade_timeline,
    get_trade_waterfall,
    get_win_loss_stats,
)

logger = logging.getLogger(__name__)


async def generate_daily_report(
    db: AsyncSession, target_date: date
) -> DailyReportResponse:
    """일일 보고서 생성 (core + analysis 통합)."""
    trades = await get_trade_timeline(db, target_date)
    stats = await get_win_loss_stats(db, target_date)
    waterfall = await get_trade_waterfall(db, target_date)
    summary = await get_daily_summary(db, target_date)

    # analysis 항목 통합 (개별 에러 시 해당 항목만 None)
    from app.services.report.analysis import (
        analyze_benchmark,
        analyze_by_time_zone,
        analyze_entry_quality,
        analyze_missed_opportunities,
        analyze_repeated_trades,
        analyze_trade_frequency,
        analyze_volatility_capture,
        get_hold_summary,
    )

    analysis: dict = {}

    async def _safe(key: str, coro):
        try:
            analysis[key] = await coro
        except Exception:
            logger.exception("analysis[%s] failed", key)
            analysis[key] = None

    await _safe(
        "missed_opportunities",
        analyze_missed_opportunities(db, target_date),
    )

    # 시간대별 분석은 tuple 반환
    try:
        tz_stats, inactive = await analyze_by_time_zone(db, target_date)
        analysis["time_zone_stats"] = tz_stats
        analysis["inactive_zone_stats"] = inactive
    except Exception:
        logger.exception("analysis[time_zone] failed")
        analysis["time_zone_stats"] = None
        analysis["inactive_zone_stats"] = None

    await _safe("hold_summary", get_hold_summary(db, target_date))
    await _safe(
        "volatility_capture",
        analyze_volatility_capture(db, target_date),
    )
    await _safe("benchmark", analyze_benchmark(db, target_date))
    await _safe(
        "repeated_trades",
        analyze_repeated_trades(db, target_date),
    )
    await _safe(
        "trade_frequency",
        analyze_trade_frequency(db, target_date),
    )
    await _safe(
        "entry_quality",
        analyze_entry_quality(db, target_date),
    )

    # advanced 분석 항목 통합
    from app.services.report.advanced import (
        analyze_llm_sources,
        analyze_orderbook_effectiveness,
    )

    await _safe("llm_source_review", analyze_llm_sources(db, target_date))
    await _safe(
        "orderbook_analysis",
        analyze_orderbook_effectiveness(db, target_date),
    )

    # 누적 지표 통합
    from app.services.report.cumulative import (
        get_cumulative_stats,
        get_rolling_stats,
    )

    cumulative = None
    rolling = None
    try:
        cumulative = await get_cumulative_stats(db, target_date)
    except Exception:
        logger.exception("cumulative stats failed")

    try:
        rolling = await get_rolling_stats(db, target_date)
    except Exception:
        logger.exception("rolling stats failed")

    # 경고 생성
    from app.services.report.alerts import generate_alerts

    alerts = []
    try:
        report_for_alerts = DailyReportResponse(
            summary=summary,
            trades=trades,
            waterfall=waterfall,
            win_loss_stats=stats,
            analysis=analysis,
            cumulative=cumulative,
            rolling=rolling,
        )
        alerts = await generate_alerts(db, report_for_alerts)
    except Exception:
        logger.exception("alerts generation failed")

    return DailyReportResponse(
        summary=summary,
        trades=trades,
        waterfall=waterfall,
        win_loss_stats=stats,
        analysis=analysis,
        cumulative=cumulative,
        rolling=rolling,
        alerts=alerts,
    )


__all__ = [
    "generate_daily_report",
    "get_daily_summary",
    "get_trade_timeline",
    "get_trade_waterfall",
    "get_win_loss_stats",
]
