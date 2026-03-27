"""alerts.py 테스트 — 경고 규칙 엔진.

PostgreSQL (asyncpg) 기반 — 기존 conftest의 TEST_DATABASE_URL 활용.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.schemas.report import (
    AlertItem,
    CumulativeStats,
    DailyReportResponse,
    DailyReportSummary,
    HoldReviewItem_41,
    HoldReviewSummary,
    MissedOpportunityItem,
    RepeatedTradeItem,
    TradeFrequencyStats,
    TradeTimelineItem,
    WinLossStats,
)
from app.services.report.alerts import (
    _sort_alerts,
    generate_alerts,
)

TEST_DATE = date(2026, 3, 26)

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/alt_fast_test"

_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def _setup_tables():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    await _engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(_setup_tables):
    async with _session_factory() as sess:
        yield sess


# ── 헬퍼 ────────────────────────────────────────────────────────


def _empty_summary(target_date: str = "2026-03-26") -> DailyReportSummary:
    return DailyReportSummary(date=target_date, is_simulated=True)


def _empty_report(target_date: str = "2026-03-26", **kwargs) -> DailyReportResponse:
    return DailyReportResponse(
        summary=kwargs.pop("summary", _empty_summary(target_date)),
        **kwargs,
    )


def _make_trade(
    time_zone_tag: str = "오전장",
    profit_loss_net: float = 1000.0,
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    **kwargs,
) -> TradeTimelineItem:
    return TradeTimelineItem(
        sell_order_id=1,
        stock_code=stock_code,
        stock_name=stock_name,
        buy_price=70000,
        sell_price=71000,
        quantity=10,
        time_zone_tag=time_zone_tag,
        profit_loss_net=profit_loss_net,
        **kwargs,
    )


def _make_decision(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    decision: str = "HOLD",
    created_at: datetime | None = None,
) -> DecisionHistory:
    return DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision=decision,
        processing_time_ms=500,
        created_at=created_at or datetime(2026, 3, 26, 9, 10, 0),
    )


def _make_sell_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    profit_loss_net: float = 1000.0,
    decision_history_id: int = 1,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = executed_at or datetime(2026, 3, 26, 9, 30, 0)
    return OrderHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="SELL",
        order_price=71000,
        order_quantity=10,
        order_total_amount=710000,
        result_price=71000,
        result_quantity=10,
        result_total_amount=710000,
        decision_history_id=decision_history_id,
        profit_loss=profit_loss_net * 1.1,
        profit_rate=1.5,
        profit_loss_net=profit_loss_net,
        profit_rate_net=1.2,
        order_placed_at=placed,
        result_executed_at=placed,
    )


def _make_buy_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    decision_history_id: int = 1,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = executed_at or datetime(2026, 3, 26, 9, 11, 0)
    return OrderHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="BUY",
        order_price=70000,
        order_quantity=10,
        order_total_amount=700000,
        result_price=70000,
        result_quantity=10,
        result_total_amount=700000,
        decision_history_id=decision_history_id,
        order_placed_at=placed,
        result_executed_at=placed,
    )


# ── 1. test_alert_lunch_time_trades ────────────────────────────


async def test_alert_lunch_time_trades(session: AsyncSession):
    """점심시간 매매 4건 -> INFO 경고 생성."""
    trades = [
        _make_trade(time_zone_tag="점심", profit_loss_net=100),
        _make_trade(time_zone_tag="점심", profit_loss_net=-50),
        _make_trade(time_zone_tag="점심", profit_loss_net=200),
        _make_trade(time_zone_tag="점심", profit_loss_net=-100),
        _make_trade(time_zone_tag="오전장", profit_loss_net=500),
    ]
    report = _empty_report(trades=trades)

    alerts = await generate_alerts(session, report)

    lunch_alerts = [a for a in alerts if a.category == "time_zone" and "점심" in a.message]
    assert len(lunch_alerts) >= 1
    assert lunch_alerts[0].type == "INFO"
    assert "4건" in lunch_alerts[0].message


# ── 2. test_alert_mdd_exceed ──────────────────────────────────


async def test_alert_mdd_exceed(session: AsyncSession):
    """일중 MDD -4% -> CRITICAL 경고."""
    summary = DailyReportSummary(
        date="2026-03-26",
        intraday_mdd=4.0,  # 양수로 저장 (절대값), 내부에서 -4%로 변환
        is_simulated=True,
    )
    report = _empty_report(summary=summary)

    alerts = await generate_alerts(session, report)

    mdd_alerts = [a for a in alerts if a.category == "mdd"]
    assert len(mdd_alerts) == 1
    assert mdd_alerts[0].type == "CRITICAL"
    assert "-4.00%" in mdd_alerts[0].message


# ── 3. test_alert_negative_expectancy ─────────────────────────


async def test_alert_negative_expectancy(session: AsyncSession):
    """누적 기대값 음수, 100건+ -> CRITICAL."""
    cumulative = CumulativeStats(
        cumulative_win_rate=45.0,
        cumulative_expected_value=-500,
        total_trades=120,
    )
    report = _empty_report(cumulative=cumulative)

    alerts = await generate_alerts(session, report)

    strategy_alerts = [a for a in alerts if a.category == "strategy" and "기대값" in a.message]
    assert len(strategy_alerts) == 1
    assert strategy_alerts[0].type == "CRITICAL"
    assert "120건" in strategy_alerts[0].message


# ── 4. test_alert_repeated_trades ─────────────────────────────


async def test_alert_repeated_trades(session: AsyncSession):
    """동일종목 3회 수익 감소 -> WARNING."""
    repeated = [
        RepeatedTradeItem(
            stock_code="005930",
            stock_name="삼성전자",
            round_count=3,
            per_round_returns=[2.0, 1.0, 0.5],
            cumulative_fee=1500,
            warning=True,
            warning_reason="수익 체감",
        ),
    ]
    report = _empty_report(analysis={"repeated_trades": repeated})

    alerts = await generate_alerts(session, report)

    rpt_alerts = [a for a in alerts if a.category == "repeated_trade"]
    assert len(rpt_alerts) == 1
    assert rpt_alerts[0].type == "WARNING"
    assert "삼성전자" in rpt_alerts[0].message
    assert "3회" in rpt_alerts[0].message


# ── 5. test_alert_fee_ratio_high ──────────────────────────────


async def test_alert_fee_ratio_high(session: AsyncSession):
    """수수료 비중 65% -> WARNING."""
    freq = TradeFrequencyStats(
        total_decisions=50,
        buy_decisions=20,
        buy_executions=15,
        fee_ratio=65.0,
        fee_grade="경고",
    )
    report = _empty_report(analysis={"trade_frequency": freq})

    alerts = await generate_alerts(session, report)

    fee_alerts = [a for a in alerts if a.category == "fee"]
    assert len(fee_alerts) == 1
    assert fee_alerts[0].type == "WARNING"
    assert "65.0%" in fee_alerts[0].message


# ── 6. test_alert_no_alerts ──────────────────────────────────


async def test_alert_no_alerts(session: AsyncSession):
    """정상 보고서 -> 빈 alerts."""
    trades = [
        _make_trade(time_zone_tag="오전장", profit_loss_net=1000),
        _make_trade(time_zone_tag="오후장", profit_loss_net=500),
    ]
    report = _empty_report(trades=trades)

    alerts = await generate_alerts(session, report)

    # 점심 매매 0건, MDD 없음, 누적 없음 등 -> 경고 없어야 함
    assert alerts == []


# ── 7. test_alert_consecutive_days ─────────────────────────────


async def test_alert_consecutive_days(session: AsyncSession):
    """3일 연속 데이터로 '3일 연속' 조건 검증 (HOLD 비율)."""
    # 3일간 HOLD 80% (8/10) 데이터 삽입
    test_dates = [date(2026, 3, 15), date(2026, 3, 16), date(2026, 3, 17)]

    for d in test_dates:
        buy_dec_id = None
        for i in range(10):
            decision = "HOLD" if i < 8 else "BUY"
            dec = _make_decision(
                decision=decision,
                created_at=datetime(d.year, d.month, d.day, 9, 10 + i, 0),
            )
            session.add(dec)
            await session.flush()
            if decision == "BUY" and buy_dec_id is None:
                buy_dec_id = dec.id

        # SELL 주문 (매매일 인식용) — 실제 decision id 사용
        buy = _make_buy_order(
            decision_history_id=buy_dec_id,
            executed_at=datetime(d.year, d.month, d.day, 10, 0, 0),
        )
        session.add(buy)
        await session.flush()
        sell = _make_sell_order(
            decision_history_id=buy_dec_id,
            profit_loss_net=100,
            executed_at=datetime(d.year, d.month, d.day, 10, 30, 0),
        )
        session.add(sell)
        await session.flush()

    report = _empty_report(target_date="2026-03-17")

    alerts = await generate_alerts(session, report)

    hold_alerts = [a for a in alerts if a.category == "hold" and "보수적" in a.action]
    assert len(hold_alerts) >= 1
    assert hold_alerts[0].type == "WARNING"


# ── 8. test_multiple_alerts_sorted ─────────────────────────────


async def test_multiple_alerts_sorted(session: AsyncSession):
    """여러 경고 -> CRITICAL > WARNING > INFO 순 정렬."""
    # MDD 초과 (CRITICAL) + 수수료 (WARNING) + 점심 매매 (INFO)
    summary = DailyReportSummary(
        date="2026-03-26",
        intraday_mdd=5.0,
        is_simulated=True,
    )
    trades = [
        _make_trade(time_zone_tag="점심"),
        _make_trade(time_zone_tag="점심"),
        _make_trade(time_zone_tag="점심"),
    ]
    freq = TradeFrequencyStats(
        total_decisions=50,
        buy_decisions=20,
        buy_executions=15,
        fee_ratio=70.0,
        fee_grade="위험",
    )
    report = _empty_report(
        summary=summary,
        trades=trades,
        analysis={"trade_frequency": freq},
    )

    alerts = await generate_alerts(session, report)

    assert len(alerts) >= 3

    # 정렬 확인: CRITICAL 먼저, 그 다음 WARNING, 마지막 INFO
    types = [a.type for a in alerts]
    critical_idx = [i for i, t in enumerate(types) if t == "CRITICAL"]
    warning_idx = [i for i, t in enumerate(types) if t == "WARNING"]
    info_idx = [i for i, t in enumerate(types) if t == "INFO"]

    if critical_idx and warning_idx:
        assert max(critical_idx) < min(warning_idx)
    if warning_idx and info_idx:
        assert max(warning_idx) < min(info_idx)
    if critical_idx and info_idx:
        assert max(critical_idx) < min(info_idx)
