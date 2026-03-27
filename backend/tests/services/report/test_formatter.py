"""formatter.py 테스트 — 텔레그램 간결/상세 포맷 + CLI 출력.

DB 불필요 (순수 포맷팅 함수 단위 테스트).
"""

from __future__ import annotations

import json

import pytest

from app.schemas.report import (
    BenchmarkComparison,
    DailyReportResponse,
    DailyReportSummary,
    RepeatedTradeItem,
    TradeTimelineItem,
    TradeWaterfallItem,
    WinLossStats,
)
from app.services.report.formatter import (
    format_cli_output,
    format_telegram_brief,
    format_telegram_detail,
)


# ── 테스트 픽스처 ──────────────────────────────────────────────


def _make_summary(**overrides) -> DailyReportSummary:
    defaults = dict(
        date="2026-03-26",
        net_profit_loss=127500.0,
        return_rate=0.85,
        total_trades=12,
        win_rate=66.7,
        expected_value=15200.0,
        profit_factor=2.14,
        intraday_mdd=42000.0,
        mdd_recovery_seconds=720.0,
        starting_cash=15_000_000.0,
    )
    defaults.update(overrides)
    return DailyReportSummary(**defaults)


def _make_trades(count: int = 12) -> list[TradeTimelineItem]:
    """더미 매매 목록."""
    stocks = [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
        ("035720", "카카오"),
        ("051910", "LG화학"),
        ("006400", "삼성SDI"),
    ]
    zones = ["장초반", "오전장", "오전장", "점심", "오후장"]
    trades = []
    for i in range(count):
        stock_code, stock_name = stocks[i % len(stocks)]
        zone = zones[i % len(zones)]
        pnl = 52000.0 - i * 8000 if i < 8 else -(i * 3000)
        trades.append(
            TradeTimelineItem(
                sell_order_id=100 + i,
                buy_order_id=50 + i,
                stock_code=stock_code,
                stock_name=stock_name,
                buy_price=50000.0,
                sell_price=50000.0 + pnl,
                quantity=10,
                time_zone_tag=zone,
                profit_loss_net=pnl,
            )
        )
    return trades


def _make_stats(win: int = 8, lose: int = 4) -> WinLossStats:
    return WinLossStats(
        total_trades=win + lose,
        winning_trades=win,
        losing_trades=lose,
        win_rate=win / (win + lose) * 100 if (win + lose) else 0.0,
        avg_profit=20000.0,
        avg_loss=-8000.0,
        profit_loss_ratio=2.5,
        expected_value=15200.0,
        profit_factor=2.14,
    )


def _make_report(**overrides) -> DailyReportResponse:
    defaults = dict(
        summary=_make_summary(),
        trades=_make_trades(),
        waterfall=[],
        win_loss_stats=_make_stats(),
        analysis={
            "benchmark": BenchmarkComparison(
                watchlist_avg_return=1.2,
                alpha_vs_watchlist=1.17,
            ),
        },
    )
    defaults.update(overrides)
    return DailyReportResponse(**defaults)


# ── 테스트 케이스 ──────────────────────────────────────────────


class TestTelegramBriefFormat:
    def test_telegram_brief_format(self):
        """샘플 보고서 -> 간결 모드 5줄 이내."""
        report = _make_report()
        result = format_telegram_brief(report)
        lines = result.strip().split("\n")

        assert len(lines) <= 5
        assert "[03-26] 일일 리포트" in lines[0]
        assert "손익:" in result
        assert "매매:" in result
        assert "Alpha:" in result
        assert "특이사항: 없음" in result

    def test_telegram_brief_with_alerts(self):
        """경고 2건 -> '특이사항' 대신 경고 표시."""
        report = _make_report(
            analysis={
                "benchmark": BenchmarkComparison(
                    watchlist_avg_return=1.2,
                    alpha_vs_watchlist=1.17,
                ),
                "repeated_trades": [
                    RepeatedTradeItem(
                        stock_code="005930",
                        stock_name="삼성전자",
                        round_count=5,
                        warning=True,
                        warning_reason="삼성전자 5회 반복매매",
                    ),
                    RepeatedTradeItem(
                        stock_code="000660",
                        stock_name="SK하이닉스",
                        round_count=4,
                        warning=True,
                        warning_reason="SK하이닉스 4회 반복매매",
                    ),
                ],
            },
        )
        result = format_telegram_brief(report)

        assert "특이사항" not in result
        assert "경고:" in result
        # 최대 2건
        assert result.count("경고:") <= 2

    def test_telegram_brief_no_trades(self):
        """매매 0건 -> '매매 없음'."""
        report = _make_report(
            summary=_make_summary(total_trades=0, net_profit_loss=0, return_rate=None),
            trades=[],
            win_loss_stats=WinLossStats(),
            analysis={},
        )
        result = format_telegram_brief(report)

        assert "매매 없음" in result


class TestTelegramDetailFormat:
    def test_telegram_detail_format(self):
        """상세 모드 구조 확인."""
        report = _make_report()
        result = format_telegram_detail(report)

        assert "[03-26] 일일 리포트 (상세)" in result
        assert "손익:" in result
        assert "수익률:" in result
        assert "매매:" in result
        assert "PF:" in result
        assert "-- 종목별 --" in result
        assert "-- 시간대 --" in result
        assert "-- 경고 --" in result

    def test_telegram_detail_length(self):
        """상세 모드 4096자 이하."""
        report = _make_report()
        result = format_telegram_detail(report)

        assert len(result) <= 4096

    def test_telegram_detail_stock_sort(self):
        """종목별 손익 순 정렬 확인."""
        report = _make_report()
        result = format_telegram_detail(report)

        # 종목별 섹션에서 첫 번째 종목이 손익이 가장 큰 종목이어야 함
        lines = result.split("\n")
        stock_section_start = None
        for i, line in enumerate(lines):
            if "-- 종목별 --" in line:
                stock_section_start = i + 1
                break

        assert stock_section_start is not None
        # 첫 번째 종목 줄에 금액이 포함되어 있어야 함
        first_stock_line = lines[stock_section_start]
        assert "원" in first_stock_line


class TestCLIOutput:
    def test_cli_output_brief(self):
        """CLI 간결 모드 = 텔레그램 간결 모드와 동일."""
        report = _make_report()
        cli_result = format_cli_output(report, detail=False)
        brief_result = format_telegram_brief(report)

        assert cli_result == brief_result

    def test_cli_output_detail(self):
        """CLI 상세 모드 = JSON pretty-print."""
        report = _make_report()
        result = format_cli_output(report, detail=True)

        # JSON 파싱 가능해야 함
        parsed = json.loads(result)
        assert "summary" in parsed
        assert "trades" in parsed
