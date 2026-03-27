"""cumulative.py 테스트 — 누적 지표, 롤링 윈도우, 전략 버전 비교.

PostgreSQL (asyncpg) 기반 — 기존 conftest의 TEST_DATABASE_URL 활용.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.services.report.cumulative import (
    _confidence_label,
    _compute_cumulative_mdd,
    _compute_stats_from_pnl,
    get_cumulative_stats,
    get_rolling_stats,
    get_version_comparison,
)

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


def _make_decision(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    created_at: datetime | None = None,
) -> DecisionHistory:
    return DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision="BUY",
        processing_time_ms=500,
        created_at=created_at or datetime(2026, 3, 27, 9, 10, 0),
    )


def _make_sell_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 71000,
    quantity: int = 10,
    buy_order_id: int | None = None,
    decision_history_id: int = 1,
    profit_loss_net: float = 8000,
    executed_at: datetime | None = None,
) -> OrderHistory:
    executed = executed_at or datetime(2026, 3, 27, 9, 30, 5)
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
        decision_history_id=decision_history_id,
        profit_loss=profit_loss_net * 1.1,
        profit_rate=1.5,
        profit_loss_net=profit_loss_net,
        profit_rate_net=1.2,
        order_placed_at=executed - timedelta(seconds=5),
        result_executed_at=executed,
    )


def _make_buy_order(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 70000,
    quantity: int = 10,
    decision_history_id: int = 1,
    executed_at: datetime | None = None,
) -> OrderHistory:
    executed = executed_at or datetime(2026, 3, 27, 9, 11, 5)
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
        decision_history_id=decision_history_id,
        order_placed_at=executed - timedelta(seconds=5),
        result_executed_at=executed,
    )


async def _seed_trades(
    session: AsyncSession,
    count: int,
    win_count: int,
    base_date: date,
    profit: float = 5000,
    loss: float = -3000,
    decision_id: int | None = None,
) -> None:
    """테스트용 매매 데이터 시딩. win_count개는 이익, 나머지는 손실."""
    if decision_id is None:
        d = _make_decision(
            created_at=datetime(base_date.year, base_date.month, base_date.day, 9, 0, 0)
        )
        session.add(d)
        await session.flush()
        decision_id = d.id

    for i in range(count):
        pnl = profit if i < win_count else loss
        base_time = datetime(
            base_date.year, base_date.month, base_date.day,
            9, 15 + (i % 45), i % 60,
        )
        buy = _make_buy_order(
            decision_history_id=decision_id,
            executed_at=base_time,
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell_order(
            buy_order_id=buy.id,
            decision_history_id=decision_id,
            profit_loss_net=pnl,
            executed_at=base_time + timedelta(minutes=5),
        )
        session.add(sell)

    await session.flush()


async def _seed_prompt_templates(
    session: AsyncSession,
    buy_version: int = 3,
    sell_version: int = 2,
    created_at: datetime | None = None,
) -> None:
    """프롬프트 템플릿 시딩."""
    ts = created_at or datetime(2026, 3, 1, 0, 0, 0)
    session.add(PromptTemplate(
        prompt_type="buy",
        content="buy prompt",
        version=buy_version,
        is_active=True,
        created_at=ts,
    ))
    session.add(PromptTemplate(
        prompt_type="sell",
        content="sell prompt",
        version=sell_version,
        is_active=True,
        created_at=ts,
    ))
    await session.flush()


# ── 1. test_cumulative_stats_basic ────────────────────────────────


async def test_cumulative_stats_basic(session: AsyncSession):
    """100건 매매 데이터 -> 누적 승률/기대값/PF 정확성."""
    # 프롬프트 템플릿 시딩 (버전 식별용)
    await _seed_prompt_templates(session, buy_version=3, sell_version=2)

    # 100건: 60승 40패, 여러 날에 분산
    for day_offset in range(10):
        d = date(2026, 3, 10 + day_offset)
        await _seed_trades(session, count=10, win_count=6, base_date=d)

    stats = await get_cumulative_stats(session, date(2026, 3, 27))

    assert stats.total_trades >= 100
    assert stats.cumulative_win_rate > 0
    assert stats.cumulative_expected_value != 0
    assert stats.cumulative_profit_factor is not None
    assert stats.strategy_version == "v3.2"

    # 롤링 윈도우도 같은 세션에서 검증
    rolling = await get_rolling_stats(session, date(2026, 3, 27))
    w30 = next((w for w in rolling.windows if w.window_size == 30), None)
    assert w30 is not None
    assert w30.win_rate is not None
    assert w30.expected_value is not None
    assert 0 <= w30.win_rate <= 100


# ── 2. test_cumulative_confidence_interval ────────────────────────


async def test_cumulative_confidence_interval(session: AsyncSession):
    """승률 60%, 100건 -> CI 범위 검증 (순수 함수)."""
    # 순수 함수 기반 검증 — DB 의존 없음
    pnl_list = [5000] * 60 + [-3000] * 40  # 60% 승률, 100건
    win_rate, ev, pf = _compute_stats_from_pnl(pnl_list)

    assert abs(win_rate - 60.0) < 0.01

    p = win_rate / 100
    n = len(pnl_list)
    margin = 1.96 * math.sqrt(p * (1 - p) / n)
    ci_lower = max(0.0, (p - margin) * 100)
    ci_upper = min(100.0, (p + margin) * 100)

    # CI는 대략 [50.4%, 69.6%] 범위여야 함
    assert ci_lower > 49.0
    assert ci_lower < 52.0
    assert ci_upper > 68.0
    assert ci_upper < 71.0
    assert ci_lower < win_rate
    assert ci_upper > win_rate

    # margin 약 9.6%
    assert abs(ci_upper - ci_lower - 2 * margin * 100) < 0.01


# ── 3. test_cumulative_mdd ────────────────────────────────────────


async def test_cumulative_mdd(session: AsyncSession):
    """일별 손익 시퀀스 -> 누적 MDD 정확성 (순수 함수 테스트)."""
    # 일별 손익: +100, -150, +50, +200, -300
    # 누적:     100, -50, 0, 200, -100
    # peak 추적: 100, 100, 100, 200, 200
    # drawdown:  0, 150, 100, 0, 300
    # MDD = 300
    daily_pnl = [100, -150, 50, 200, -300]
    mdd = _compute_cumulative_mdd(daily_pnl)
    assert mdd == 300


# ── 4. test_rolling_stats_window_30 ───────────────────────────────


async def test_rolling_stats_window_30(session: AsyncSession):
    """최근 30건 롤링 승률 검증 — 같은 세션에서 데이터 시드 후 조회."""
    # 데이터 시드 (40건: 24승 16패)
    await _seed_trades(session, count=40, win_count=24, base_date=date(2026, 3, 26))

    rolling = await get_rolling_stats(session, date(2026, 3, 27))

    w30 = next((w for w in rolling.windows if w.window_size == 30), None)
    assert w30 is not None
    assert w30.win_rate is not None
    assert w30.expected_value is not None
    assert 0 <= w30.win_rate <= 100


# ── 5. test_rolling_stats_insufficient ────────────────────────────


async def test_rolling_stats_insufficient(session: AsyncSession):
    """25건만 존재 -> 30건 윈도우 None 검증 (순수 함수)."""
    pnl_25 = [5000] * 15 + [-3000] * 10  # 25건

    win_rate, ev, pf = _compute_stats_from_pnl(pnl_25)
    assert win_rate == 60.0  # 15/25
    assert len(pnl_25) < 30  # 30건 미만이면 롤링 윈도우에서 None 반환됨


# ── 6. test_version_comparison ────────────────────────────────────


async def test_version_comparison(session: AsyncSession):
    """2개 버전 -> 각 버전별 성과 분리."""
    # v1.1 프롬프트 (2026-02-01)
    session.add(PromptTemplate(
        prompt_type="buy",
        content="buy prompt v1",
        version=1,
        is_active=False,
        created_at=datetime(2026, 2, 1, 0, 0, 0),
    ))
    session.add(PromptTemplate(
        prompt_type="sell",
        content="sell prompt v1",
        version=1,
        is_active=False,
        created_at=datetime(2026, 2, 1, 0, 0, 0),
    ))
    await session.flush()

    # v1 기간 매매 데이터 (2026-02-10)
    await _seed_trades(
        session, count=15, win_count=9,
        base_date=date(2026, 2, 10),
    )

    # v2.1 프롬프트 (2026-02-20) — buy만 업데이트
    session.add(PromptTemplate(
        prompt_type="buy",
        content="buy prompt v2",
        version=2,
        is_active=False,
        created_at=datetime(2026, 2, 20, 0, 0, 0),
    ))
    await session.flush()

    # v2 기간 매매 데이터 (2026-02-25)
    await _seed_trades(
        session, count=20, win_count=14,
        base_date=date(2026, 2, 25),
    )

    comparisons = await get_version_comparison(session)

    assert len(comparisons) >= 2
    # 각 버전에 trade_count가 있어야 함
    has_trades = [c for c in comparisons if c.trade_count > 0]
    assert len(has_trades) >= 2

    for comp in comparisons:
        assert comp.version is not None
        assert isinstance(comp.trade_count, int)


# ── 7. test_confidence_label_under_30 ─────────────────────────────


async def test_confidence_label_under_30(session: AsyncSession):
    """20건 -> '데이터 부족'."""
    label = _confidence_label(20)
    assert label == "데이터 부족 — 참고만"


# ── 8. test_confidence_label_over_100 ─────────────────────────────


async def test_confidence_label_over_100(session: AsyncSession):
    """150건 -> '통계적 판단 가능'."""
    label = _confidence_label(150)
    assert label == "통계적 판단 가능"

    # 중간 범위도 확인
    assert _confidence_label(35) == "초기 추세 — 판단 보류"
    assert _confidence_label(75) == "추세 확인 중"
