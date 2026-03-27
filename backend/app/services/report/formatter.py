"""보고서 텔레그램/CLI 포맷팅 + 전송."""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.report import DailyReportResponse
from app.shared.telegram import send_message

logger = logging.getLogger(__name__)

TELEGRAM_CHAR_LIMIT = 4096


def _fmt_money(value: float | None) -> str:
    """금액 포맷: +127,500원 / -12,300원."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:,.0f}원"


def _fmt_pct(value: float | None) -> str:
    """퍼센트 포맷: +0.85% / -1.20%."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _extract_date_str(report: DailyReportResponse) -> str:
    """보고서에서 MM-DD 형식 날짜 추출."""
    date_str = report.summary.date  # "2026-03-26"
    try:
        parts = date_str.split("-")
        return f"{parts[1]}-{parts[2]}"
    except (IndexError, AttributeError):
        return date_str


def _get_alerts(report: DailyReportResponse) -> list[str]:
    """보고서에서 경고 메시지 추출."""
    alerts: list[str] = []
    analysis = report.analysis or {}

    # 반복매매 경고
    repeated = analysis.get("repeated_trades")
    if repeated and isinstance(repeated, list):
        for item in repeated:
            if hasattr(item, "warning") and item.warning:
                reason = getattr(item, "warning_reason", None) or "반복매매 경고"
                alerts.append(reason)

    # 매매빈도 수수료 경고
    freq = analysis.get("trade_frequency")
    if freq and hasattr(freq, "fee_grade"):
        if freq.fee_grade in ("경고", "위험"):
            alerts.append(f"수수료 비중 {freq.fee_grade}: {_fmt_pct(freq.fee_ratio)}")

    # 시간대별 경고
    tz_stats = analysis.get("time_zone_stats")
    if tz_stats and isinstance(tz_stats, list):
        for tz in tz_stats:
            if hasattr(tz, "warnings"):
                for w in tz.warnings:
                    alerts.append(w)

    return alerts


def _get_stock_pnl(report: DailyReportResponse) -> list[tuple[str, float, int]]:
    """종목별 (종목명, 손익합계, 건수) 리스트, 손익 순 정렬."""
    stock_map: dict[str, tuple[float, int]] = {}
    for t in report.trades:
        pnl = t.profit_loss_net or 0.0
        name = t.stock_name
        if name in stock_map:
            prev_pnl, prev_cnt = stock_map[name]
            stock_map[name] = (prev_pnl + pnl, prev_cnt + 1)
        else:
            stock_map[name] = (pnl, 1)
    result = [(name, pnl, cnt) for name, (pnl, cnt) in stock_map.items()]
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def _get_time_zone_pnl(report: DailyReportResponse) -> list[tuple[str, float, int]]:
    """시간대별 (시간대명, 손익합계, 건수) 리스트."""
    tz_map: dict[str, tuple[float, int]] = {}
    for t in report.trades:
        zone = t.time_zone_tag or "기타"
        pnl = t.profit_loss_net or 0.0
        if zone in tz_map:
            prev_pnl, prev_cnt = tz_map[zone]
            tz_map[zone] = (prev_pnl + pnl, prev_cnt + 1)
        else:
            tz_map[zone] = (pnl, 1)
    result = [(zone, pnl, cnt) for zone, (pnl, cnt) in tz_map.items()]
    return result


def format_telegram_brief(report: DailyReportResponse) -> str:
    """텔레그램 간결 모드 — 핵심 5줄 이내."""
    s = report.summary
    date_str = _extract_date_str(report)
    alerts = _get_alerts(report)

    lines: list[str] = []
    lines.append(f"[{date_str}] 일일 리포트")

    if s.total_trades == 0:
        lines.append("매매 없음")
    else:
        # 손익 줄
        lines.append(f"손익: {_fmt_money(s.net_profit_loss)} | 수익률 {_fmt_pct(s.return_rate)}")

        # 매매 줄
        win_count = 0
        loss_count = 0
        if report.win_loss_stats:
            win_count = report.win_loss_stats.winning_trades
            loss_count = report.win_loss_stats.losing_trades
        pf_str = f" | PF {s.profit_factor:.2f}" if s.profit_factor is not None else ""
        lines.append(f"매매: {s.total_trades}건 (승{win_count}/패{loss_count}){pf_str}")

        # Alpha 줄
        analysis = report.analysis or {}
        benchmark = analysis.get("benchmark")
        if benchmark and hasattr(benchmark, "alpha_vs_watchlist") and benchmark.alpha_vs_watchlist is not None:
            lines.append(f"Alpha: {_fmt_pct(benchmark.alpha_vs_watchlist)} (감시종목 대비)")
        else:
            lines.append("Alpha: N/A")

    # 특이사항 / 경고
    if alerts:
        for a in alerts[:2]:
            lines.append(f"경고: {a}")
    else:
        lines.append("특이사항: 없음")

    result = "\n".join(lines)
    return result[:TELEGRAM_CHAR_LIMIT]


def format_telegram_detail(report: DailyReportResponse) -> str:
    """텔레그램 상세 모드 — 역삼각형 구성."""
    s = report.summary
    stats = report.win_loss_stats
    date_str = _extract_date_str(report)
    alerts = _get_alerts(report)
    analysis = report.analysis or {}

    sections: list[str] = []

    # 헤더
    sections.append(f"[{date_str}] 일일 리포트 (상세)")
    sections.append("")

    if s.total_trades == 0:
        sections.append("매매 없음")
        return "\n".join(sections)

    # 요약 섹션
    sections.append(f"손익: {_fmt_money(s.net_profit_loss)} (세후)")

    # Alpha
    benchmark = analysis.get("benchmark")
    alpha_str = ""
    if benchmark and hasattr(benchmark, "alpha_vs_watchlist") and benchmark.alpha_vs_watchlist is not None:
        alpha_str = f" | Alpha {_fmt_pct(benchmark.alpha_vs_watchlist)} (감시종목)"
    sections.append(f"수익률: {_fmt_pct(s.return_rate)}{alpha_str}")

    # 매매
    if stats:
        win_rate_str = f"{stats.win_rate:.1f}%" if stats.win_rate is not None else "N/A"
        sections.append(
            f"매매: {stats.total_trades}건 (승{stats.winning_trades}/패{stats.losing_trades}, 승률 {win_rate_str})"
        )

        # PF + 기대값
        pf_str = f"{s.profit_factor:.2f}" if s.profit_factor is not None else "N/A"
        ev_str = _fmt_money(stats.expected_value) if stats.expected_value else "N/A"
        sections.append(f"PF: {pf_str} | 기대값: {ev_str}/건")
    else:
        sections.append(f"매매: {s.total_trades}건")

    # MDD
    if s.intraday_mdd is not None:
        mdd_pct = _fmt_pct(-abs(s.intraday_mdd)) if s.intraday_mdd != 0 else "0.00%"
        recovery_str = ""
        if s.mdd_recovery_seconds is not None:
            mins = int(s.mdd_recovery_seconds / 60)
            recovery_str = f" (회복 {mins}분)"
        sections.append(f"MDD: {mdd_pct}{recovery_str}")

    # 종목별 섹션
    stock_pnl = _get_stock_pnl(report)
    if stock_pnl:
        sections.append("")
        sections.append("-- 종목별 --")
        for name, pnl, cnt in stock_pnl[:5]:
            sections.append(f"{name}: {_fmt_money(pnl)} ({cnt}건)")
        if len(stock_pnl) > 5:
            sections.append("...")

    # 시간대 섹션
    tz_pnl = _get_time_zone_pnl(report)
    if tz_pnl:
        sections.append("")
        sections.append("-- 시간대 --")
        for zone, pnl, cnt in tz_pnl:
            sections.append(f"{zone}: {_fmt_money(pnl)} ({cnt}건)")

    # 누적 섹션
    if report.cumulative and report.cumulative.total_trades > 0:
        cum = report.cumulative
        ver_str = f"전략 {cum.strategy_version}" if cum.strategy_version else ""
        ver_cnt = f", {cum.version_trade_count}건" if cum.version_trade_count else ""
        sections.append("")
        sections.append(
            f"누적 승률: {cum.cumulative_win_rate:.1f}% "
            f"({cum.total_trades}건) "
            f"[{ver_str}{ver_cnt}]"
        )

    # 경고 섹션
    sections.append("")
    sections.append("-- 경고 --")
    if alerts:
        for a in alerts[:3]:
            sections.append(a)
    else:
        sections.append("없음")

    result = "\n".join(sections)

    # 4096자 초과 시 하단부터 축약
    if len(result) > TELEGRAM_CHAR_LIMIT:
        while len(result) > TELEGRAM_CHAR_LIMIT - 10 and sections:
            sections.pop()
            result = "\n".join(sections)
        result += "\n..."

    return result[:TELEGRAM_CHAR_LIMIT]


def format_cli_output(report: DailyReportResponse, detail: bool) -> str:
    """CLI 출력 포맷.

    detail=False: 간결 모드와 동일 (터미널 폭 고려)
    detail=True: JSON pretty-print
    """
    if detail:
        return json.dumps(
            report.model_dump(),
            indent=2,
            default=str,
            ensure_ascii=False,
        )
    return format_telegram_brief(report)


async def send_report_telegram(
    report: DailyReportResponse,
    detail: bool = False,
) -> bool:
    """보고서를 텔레그램으로 전송."""
    if detail:
        message = format_telegram_detail(report)
    else:
        message = format_telegram_brief(report)
    return await send_message(message)
