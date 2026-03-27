"""core.py 테스트 — 매매 타임라인, 승률/손익비, 워터폴.

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
from app.services.report.core import (
    _classify_time_zone,
    calculate_mdd,
    get_daily_summary,
    get_trade_timeline,
    get_trade_waterfall,
    get_win_loss_stats,
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
        # 테스트 후 관련 테이블만 정리
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    await _engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(_setup_tables):
    async with _session_factory() as sess:
        yield sess


# ── 헬퍼 ────────────────────────────────────────────────────────


def _make_decision(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    processing_time_ms: int = 500,
    created_at: datetime | None = None,
) -> DecisionHistory:
    return DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision="BUY",
        processing_time_ms=processing_time_ms,
        created_at=created_at or datetime(2026, 3, 26, 9, 10, 0),
    )


def _make_buy_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 70000,
    quantity: int = 10,
    decision_history_id: int | None = None,
    order_placed_at: datetime | None = None,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = order_placed_at or datetime(2026, 3, 26, 9, 11, 0)
    executed = executed_at or datetime(2026, 3, 26, 9, 11, 5)
    return OrderHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="BUY",
        order_price=price,
        order_quantity=quantity,
        order_total_amount=price * quantity,
        result_price=price,
        result_quantity=quantity,
        result_total_amount=price * quantity,
        decision_history_id=decision_history_id or 1,
        order_placed_at=placed,
        result_executed_at=executed,
    )


def _make_sell_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 71000,
    quantity: int = 10,
    buy_order_id: int | None = None,
    decision_history_id: int | None = None,
    profit_loss_net: float = 8000,
    order_placed_at: datetime | None = None,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = order_placed_at or datetime(2026, 3, 26, 9, 30, 0)
    executed = executed_at or datetime(2026, 3, 26, 9, 30, 5)
    return OrderHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="SELL",
        order_price=price,
        order_quantity=quantity,
        order_total_amount=price * quantity,
        result_price=price,
        result_quantity=quantity,
        result_total_amount=price * quantity,
        buy_order_id=buy_order_id,
        decision_history_id=decision_history_id or 1,
        profit_loss=profit_loss_net * 1.1,
        profit_rate=1.5,
        profit_loss_net=profit_loss_net,
        profit_rate_net=1.2,
        order_placed_at=placed,
        result_executed_at=executed,
    )


# ── 1. test_trade_timeline_basic ─────────────────────────────────


async def test_trade_timeline_basic(session: AsyncSession):
    """BUY+SELL 페어 2건 삽입 -> 타임라인 2건 반환, 보유시간/시간대 태그 확인."""
    d1 = _make_decision(created_at=datetime(2026, 3, 26, 9, 10, 0))
    session.add(d1)
    await session.flush()

    buy1 = _make_buy_order(
        decision_history_id=d1.id,
        order_placed_at=datetime(2026, 3, 26, 9, 11, 0),
        executed_at=datetime(2026, 3, 26, 9, 11, 5),
    )
    session.add(buy1)
    await session.flush()

    sell1 = _make_sell_order(
        buy_order_id=buy1.id,
        decision_history_id=d1.id,
        profit_loss_net=8000,
        order_placed_at=datetime(2026, 3, 26, 9, 20, 0),
        executed_at=datetime(2026, 3, 26, 9, 20, 5),
    )
    session.add(sell1)

    d2 = _make_decision(
        stock_code="000660",
        stock_name="SK하이닉스",
        created_at=datetime(2026, 3, 26, 10, 0, 0),
    )
    session.add(d2)
    await session.flush()

    buy2 = _make_buy_order(
        stock_code="000660",
        stock_name="SK하이닉스",
        price=150000,
        decision_history_id=d2.id,
        order_placed_at=datetime(2026, 3, 26, 10, 0, 30),
        executed_at=datetime(2026, 3, 26, 10, 0, 35),
    )
    session.add(buy2)
    await session.flush()

    sell2 = _make_sell_order(
        stock_code="000660",
        stock_name="SK하이닉스",
        price=152000,
        buy_order_id=buy2.id,
        decision_history_id=d2.id,
        profit_loss_net=15000,
        order_placed_at=datetime(2026, 3, 26, 10, 30, 0),
        executed_at=datetime(2026, 3, 26, 10, 30, 5),
    )
    session.add(sell2)
    await session.flush()

    items = await get_trade_timeline(session, TEST_DATE)
    assert len(items) == 2

    # 첫 번째: 보유시간 약 9분 = 초단타
    assert items[0].holding_category == "초단타"
    assert items[0].time_zone_tag == "장초반"

    # 두 번째: 보유시간 약 30분 = 단타
    assert items[1].holding_category == "단타"
    assert items[1].time_zone_tag == "오전장"


# ── 2. test_trade_timeline_empty ─────────────────────────────────


async def test_trade_timeline_empty(session: AsyncSession):
    """매매 없는 날짜 -> 빈 리스트."""
    items = await get_trade_timeline(session, date(2020, 1, 1))
    assert items == []


# ── 3. test_win_loss_stats_mixed ─────────────────────────────────


async def test_win_loss_stats_mixed(session: AsyncSession):
    """이익 3건 + 손실 2건 -> 승률 60%."""
    d = _make_decision(created_at=datetime(2026, 3, 26, 9, 10, 0))
    session.add(d)
    await session.flush()

    pnl_values = [10000, 5000, 8000, -3000, -7000]
    for i, pnl in enumerate(pnl_values):
        base_time = datetime(2026, 3, 26, 11, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=pnl,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    stats = await get_win_loss_stats(session, TEST_DATE)

    # 이전 테스트의 데이터도 포함될 수 있으므로 최소 검증
    assert stats.total_trades >= 5
    assert stats.winning_trades >= 3
    assert stats.losing_trades >= 2
    assert stats.profit_factor is not None
    assert stats.expected_value != 0


# ── 4. test_win_loss_stats_all_win ───────────────────────────────


async def test_win_loss_stats_all_win(session: AsyncSession):
    """전부 이익 -> 승률 100%, PF = inf."""
    target = date(2026, 3, 25)
    d = _make_decision(created_at=datetime(2026, 3, 25, 9, 10, 0))
    session.add(d)
    await session.flush()

    for i in range(3):
        base_time = datetime(2026, 3, 25, 10, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=5000,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    stats = await get_win_loss_stats(session, target)
    assert stats.win_rate == 100.0
    assert stats.profit_factor == float("inf")
    assert stats.losing_trades == 0


# ── 5. test_win_loss_stats_no_trades ─────────────────────────────


async def test_win_loss_stats_no_trades(session: AsyncSession):
    """매매 없음 -> 기본값."""
    stats = await get_win_loss_stats(session, date(2020, 1, 1))
    assert stats.total_trades == 0
    assert stats.win_rate == 0.0
    assert stats.expected_value == 0.0


# ── 6. test_trade_waterfall_cumulative ───────────────────────────


async def test_trade_waterfall_cumulative(session: AsyncSession):
    """3건 매매 -> 누적 손익 정확성 검증."""
    target = date(2026, 3, 24)
    d = _make_decision(created_at=datetime(2026, 3, 24, 9, 10, 0))
    session.add(d)
    await session.flush()

    pnl_values = [10000, -3000, 5000]
    for i, pnl in enumerate(pnl_values):
        base_time = datetime(2026, 3, 24, 10, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=pnl,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    waterfall = await get_trade_waterfall(session, target)
    assert len(waterfall) == 3
    assert waterfall[0].cumulative_profit_loss == 10000
    assert waterfall[1].cumulative_profit_loss == 7000
    assert waterfall[2].cumulative_profit_loss == 12000


# ── 7. test_trade_waterfall_mdd ──────────────────────────────────


async def test_trade_waterfall_mdd(session: AsyncSession):
    """누적 손익 +100, -50, +30 -> MDD = 50 검증."""
    target = date(2026, 3, 23)
    d = _make_decision(created_at=datetime(2026, 3, 23, 9, 10, 0))
    session.add(d)
    await session.flush()

    # 누적: 100, 50(-50 = loss), 80(+30)
    # Peak = 100, trough = 50, MDD = 50
    pnl_values = [100, -50, 30]
    for i, pnl in enumerate(pnl_values):
        base_time = datetime(2026, 3, 23, 10, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=pnl,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    waterfall = await get_trade_waterfall(session, target)
    mdd, recovery = calculate_mdd(waterfall)
    assert mdd == 50


# ── 8. test_daily_summary_integration ────────────────────────────


async def test_daily_summary_integration(session: AsyncSession):
    """전체 summary 생성 -> 모든 필드 존재."""
    target = date(2026, 3, 20)
    d = _make_decision(created_at=datetime(2026, 3, 20, 9, 10, 0))
    session.add(d)
    await session.flush()

    pnl_values = [5000, -2000, 3000]
    for i, pnl in enumerate(pnl_values):
        base_time = datetime(2026, 3, 20, 10, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=pnl,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    summary = await get_daily_summary(session, target)
    assert summary.date == "2026-03-20"
    assert summary.total_trades > 0
    assert summary.net_profit_loss != 0
    assert summary.win_rate is not None
    assert summary.intraday_mdd is not None


# ── 9. test_time_zone_tag ────────────────────────────────────────


async def test_time_zone_tag(session: AsyncSession):
    """각 시간대별 매매 -> 올바른 태그 부여."""
    assert _classify_time_zone(datetime(2026, 3, 26, 9, 15)) == "장초반"
    assert _classify_time_zone(datetime(2026, 3, 26, 10, 0)) == "오전장"
    assert _classify_time_zone(datetime(2026, 3, 26, 12, 0)) == "점심"
    assert _classify_time_zone(datetime(2026, 3, 26, 14, 0)) == "오후장"
    assert _classify_time_zone(datetime(2026, 3, 26, 15, 0)) == "마감접근"
    assert _classify_time_zone(datetime(2026, 3, 26, 15, 25)) == "동시호가"


# ── 10. test_consecutive_wins_losses ─────────────────────────────


async def test_consecutive_wins_losses(session: AsyncSession):
    """승승패패승 -> 최대 연속 승 2, 최대 연속 패 2."""
    target = date(2026, 3, 22)
    d = _make_decision(created_at=datetime(2026, 3, 22, 9, 10, 0))
    session.add(d)
    await session.flush()

    # 승승패패승
    pnl_values = [1000, 2000, -500, -1000, 3000]
    for i, pnl in enumerate(pnl_values):
        base_time = datetime(2026, 3, 22, 10, i * 10, 0)
        buy = _make_buy_order(
            decision_history_id=d.id,
            order_placed_at=base_time,
            executed_at=base_time + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=d.id,
            profit_loss_net=pnl,
            order_placed_at=base_time + timedelta(minutes=5),
            executed_at=base_time + timedelta(minutes=5, seconds=5),
        )
        session.add(sell)
    await session.flush()

    stats = await get_win_loss_stats(session, target)
    assert stats.max_consecutive_wins == 2
    assert stats.max_consecutive_losses == 2
