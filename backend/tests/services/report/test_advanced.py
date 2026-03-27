"""advanced.py 테스트 — LLM 판단근거 복기, 호가 활용도 검증.

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
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.services.report.advanced import (
    _compute_orderbook_signal,
    _extract_source_types,
    analyze_llm_sources,
    analyze_orderbook_effectiveness,
)

# 전용 테스트 날짜 (다른 테스트와 충돌 방지)
TEST_DATE = date(2026, 3, 20)

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/alt_fast_test"

_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_session_factory = async_sessionmaker(
    _engine, class_=AsyncSession, expire_on_commit=False
)


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


def _dt(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 3, 20, hour, minute, second)


def _make_decision(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    decision: str = "BUY",
    parsed_decision: dict | None = None,
    is_error: bool = False,
    created_at: datetime | None = None,
) -> DecisionHistory:
    return DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision=decision,
        parsed_decision=parsed_decision,
        processing_time_ms=500,
        is_error=is_error,
        created_at=created_at or _dt(9, 30),
    )


def _make_buy_order(
    decision_history_id: int,
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 70000,
    quantity: int = 10,
    placed_at: datetime | None = None,
) -> OrderHistory:
    p = placed_at or _dt(9, 30)
    return OrderHistory(
        decision_history_id=decision_history_id,
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="BUY",
        order_price=price,
        order_quantity=quantity,
        order_total_amount=price * quantity,
        result_price=price,
        result_quantity=quantity,
        result_total_amount=price * quantity,
        order_placed_at=p,
        result_executed_at=p,
    )


def _make_sell_order(
    decision_history_id: int,
    buy_order_id: int,
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 71000,
    quantity: int = 10,
    pnl: float = 10000,
    placed_at: datetime | None = None,
) -> OrderHistory:
    p = placed_at or _dt(10, 0)
    return OrderHistory(
        decision_history_id=decision_history_id,
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
        profit_loss=pnl,
        profit_rate=pnl / (price * quantity) * 100 if price * quantity else 0,
        profit_loss_net=pnl * 0.85,  # 세후
        profit_rate_net=None,
        order_placed_at=p,
        result_executed_at=p,
    )


def _make_snapshot(
    stock_code: str = "005930",
    snapshot_at: datetime | None = None,
    ask_prices: tuple = (100, 101, 102, 103, 104),
    ask_volumes: tuple = (100, 100, 100, 100, 100),
    bid_prices: tuple = (99, 98, 97, 96, 95),
    bid_volumes: tuple = (100, 100, 100, 100, 100),
    total_ask: int | None = None,
    total_bid: int | None = None,
) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        stock_code=stock_code,
        snapshot_at=snapshot_at or _dt(9, 30),
        ask_price1=ask_prices[0],
        ask_price2=ask_prices[1],
        ask_price3=ask_prices[2],
        ask_price4=ask_prices[3],
        ask_price5=ask_prices[4],
        ask_volume1=ask_volumes[0],
        ask_volume2=ask_volumes[1],
        ask_volume3=ask_volumes[2],
        ask_volume4=ask_volumes[3],
        ask_volume5=ask_volumes[4],
        bid_price1=bid_prices[0],
        bid_price2=bid_prices[1],
        bid_price3=bid_prices[2],
        bid_price4=bid_prices[3],
        bid_price5=bid_prices[4],
        bid_volume1=bid_volumes[0],
        bid_volume2=bid_volumes[1],
        bid_volume3=bid_volumes[2],
        bid_volume4=bid_volumes[3],
        bid_volume5=bid_volumes[4],
        total_ask_volume=total_ask if total_ask is not None else sum(ask_volumes),
        total_bid_volume=total_bid if total_bid is not None else sum(bid_volumes),
    )


def _parsed_decision_with_sources(*source_types: str) -> dict:
    """sources 배열을 가진 parsed_decision dict 생성."""
    return {
        "decision": {
            "action": "BUY",
            "sources": [{"type": st, "weight": 1} for st in source_types],
        }
    }


# ── LLM 판단근거 복기 테스트 ─────────────────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_llm_sources_binary_classification(session: AsyncSession):
    """sources에 '기술적분석' 있는 판단 3건(승2패1), 없는 판단 2건(승0패2).

    기술적분석 언급 시 승률 66.7%, 미언급 시 0%.
    """
    # 기술적분석 언급 BUY 판단 3건
    d1 = _make_decision(parsed_decision=_parsed_decision_with_sources("기술적분석", "뉴스"), created_at=_dt(9, 31))
    d2 = _make_decision(parsed_decision=_parsed_decision_with_sources("기술적분석"), created_at=_dt(9, 32))
    d3 = _make_decision(parsed_decision=_parsed_decision_with_sources("기술적분석", "수급"), created_at=_dt(9, 33))
    # 미언급 BUY 판단 2건
    d4 = _make_decision(parsed_decision=_parsed_decision_with_sources("뉴스"), created_at=_dt(9, 34))
    d5 = _make_decision(parsed_decision=_parsed_decision_with_sources("공시"), created_at=_dt(9, 35))

    session.add_all([d1, d2, d3, d4, d5])
    await session.flush()

    # BUY 주문 생성
    b1 = _make_buy_order(d1.id, placed_at=_dt(9, 31))
    b2 = _make_buy_order(d2.id, placed_at=_dt(9, 32))
    b3 = _make_buy_order(d3.id, placed_at=_dt(9, 33))
    b4 = _make_buy_order(d4.id, placed_at=_dt(9, 34))
    b5 = _make_buy_order(d5.id, placed_at=_dt(9, 35))
    session.add_all([b1, b2, b3, b4, b5])
    await session.flush()

    # SELL 주문 (d1: 승, d2: 승, d3: 패, d4: 패, d5: 패)
    s1 = _make_sell_order(d1.id, b1.id, pnl=5000)   # 승 (pnl_net=4250)
    s2 = _make_sell_order(d2.id, b2.id, pnl=3000)   # 승
    s3 = _make_sell_order(d3.id, b3.id, pnl=-2000)  # 패
    s4 = _make_sell_order(d4.id, b4.id, pnl=-1000)  # 패
    s5 = _make_sell_order(d5.id, b5.id, pnl=-1500)  # 패
    session.add_all([s1, s2, s3, s4, s5])
    await session.commit()

    result = await analyze_llm_sources(session, TEST_DATE)

    assert result.total_buy_decisions == 5
    assert result.data_count == 5

    # 기술적분석 소스 통계 확인
    ta_stat = next((s for s in result.source_stats if s.source_type == "기술적분석"), None)
    assert ta_stat is not None
    assert ta_stat.mention_count == 3
    assert ta_stat.win_rate_with == pytest.approx(66.7, abs=0.1)
    assert ta_stat.win_rate_without == pytest.approx(0.0, abs=0.1)

    assert result.best_source == "기술적분석"


@pytest.mark.asyncio(loop_scope="session")
async def test_llm_sources_no_parsed_decision(session: AsyncSession):
    """parsed_decision이 None인 건 -> 소스 추출 시 빈 집합."""
    sources = _extract_source_types(None)
    assert sources == set()

    sources2 = _extract_source_types({})
    assert sources2 == set()


@pytest.mark.asyncio(loop_scope="session")
async def test_llm_sources_error_excluded(session: AsyncSession):
    """is_error=True인 판단은 분석에서 제외."""
    # is_error=True 판단 추가 (다른 시각으로)
    d_err = _make_decision(
        parsed_decision=_parsed_decision_with_sources("기술적분석"),
        is_error=True,
        created_at=_dt(10, 0),
    )
    session.add(d_err)
    await session.commit()

    result = await analyze_llm_sources(session, TEST_DATE)

    # is_error=True는 제외되므로 total_buy_decisions는 여전히 5
    assert result.total_buy_decisions == 5


# ── 호가 활용도 검증 테스트 ───────────────────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_orderbook_supply_demand_ratio(session: AsyncSession):
    """bid_volume 총 1000, ask_volume 총 500 -> 수급 비율 2.0."""
    snap = _make_snapshot(
        bid_volumes=(200, 200, 200, 200, 200),
        ask_volumes=(100, 100, 100, 100, 100),
        total_bid=1000,
        total_ask=500,
    )
    signal = _compute_orderbook_signal(snap)
    assert signal.supply_demand_ratio == pytest.approx(2.0, abs=0.01)


@pytest.mark.asyncio(loop_scope="session")
async def test_orderbook_spread_calculation(session: AsyncSession):
    """ask1=100, bid1=99 -> 스프레드 약 1.005%."""
    snap = _make_snapshot(
        ask_prices=(100, 101, 102, 103, 104),
        bid_prices=(99, 98, 97, 96, 95),
    )
    signal = _compute_orderbook_signal(snap)
    # (100 - 99) / ((100 + 99) / 2) * 100 = 1 / 99.5 * 100 = ~1.005%
    assert signal.spread_ratio == pytest.approx(1.005, abs=0.01)


@pytest.mark.asyncio(loop_scope="session")
async def test_orderbook_sell_wall_detection(session: AsyncSession):
    """특정 호가에 평균의 4배 잔량 -> 매도벽 True."""
    # 평균 = (400 + 100 + 100 + 100 + 100) / 5 = 160
    # 400 >= 160 * 3 = 480? No. -> 평균의 3배는 480.
    # 600이면: avg = (600+100+100+100+100)/5 = 200, 3배=600, 600>=600 True
    snap = _make_snapshot(
        ask_volumes=(600, 100, 100, 100, 100),
    )
    signal = _compute_orderbook_signal(snap)
    assert signal.sell_wall_exists is True

    # 매도벽 없는 경우
    snap2 = _make_snapshot(
        ask_volumes=(100, 100, 100, 100, 100),
    )
    signal2 = _compute_orderbook_signal(snap2)
    assert signal2.sell_wall_exists is False


@pytest.mark.asyncio(loop_scope="session")
async def test_orderbook_insufficient_data(session: AsyncSession):
    """스냅샷 10건 -> is_sufficient=False."""
    # 기존 데이터 정리를 위해 새 날짜 사용
    other_date = date(2026, 3, 21)

    # BUY 판단 + 주문 10건 생성
    for i in range(10):
        d = DecisionHistory(
            stock_code="000660",
            stock_name="SK하이닉스",
            decision="BUY",
            processing_time_ms=100,
            is_error=False,
            created_at=datetime(2026, 3, 21, 9, 30 + i),
        )
        session.add(d)
        await session.flush()

        bo = OrderHistory(
            decision_history_id=d.id,
            stock_code="000660",
            stock_name="SK하이닉스",
            order_type="BUY",
            order_price=150000,
            order_quantity=1,
            order_total_amount=150000,
            result_price=150000,
            result_quantity=1,
            result_total_amount=150000,
            order_placed_at=datetime(2026, 3, 21, 9, 30 + i),
            result_executed_at=datetime(2026, 3, 21, 9, 30 + i),
        )
        session.add(bo)
        await session.flush()

        # 호가 스냅샷
        snap = _make_snapshot(
            stock_code="000660",
            snapshot_at=datetime(2026, 3, 21, 9, 30 + i),
            total_bid=1000,
            total_ask=500,
        )
        session.add(snap)

    await session.commit()

    result = await analyze_orderbook_effectiveness(session, other_date)
    assert result.is_sufficient is False
    assert result.data_count == 10
    assert "축적" in (result.message or "")


@pytest.mark.asyncio(loop_scope="session")
async def test_orderbook_win_rate_by_supply(session: AsyncSession):
    """수급 우위 5건(승4패1), 수급 열위 5건(승1패4) -> 승률 비교."""
    test_date = date(2026, 3, 22)

    # 수급 우위 (bid > ask) 5건
    for i in range(5):
        d = DecisionHistory(
            stock_code="035420",
            stock_name="NAVER",
            decision="BUY",
            processing_time_ms=100,
            is_error=False,
            created_at=datetime(2026, 3, 22, 9, 30 + i),
        )
        session.add(d)
        await session.flush()

        bo = OrderHistory(
            decision_history_id=d.id,
            stock_code="035420",
            stock_name="NAVER",
            order_type="BUY",
            order_price=200000,
            order_quantity=1,
            order_total_amount=200000,
            result_price=200000,
            result_quantity=1,
            result_total_amount=200000,
            order_placed_at=datetime(2026, 3, 22, 9, 30 + i),
            result_executed_at=datetime(2026, 3, 22, 9, 30 + i),
        )
        session.add(bo)
        await session.flush()

        # 수급 우위 호가
        snap = _make_snapshot(
            stock_code="035420",
            snapshot_at=datetime(2026, 3, 22, 9, 30 + i),
            total_bid=2000,
            total_ask=1000,
        )
        session.add(snap)
        await session.flush()

        # SELL: 승4패1
        pnl = 5000 if i < 4 else -3000
        so = OrderHistory(
            decision_history_id=d.id,
            stock_code="035420",
            stock_name="NAVER",
            order_type="SELL",
            order_price=201000 if pnl > 0 else 199000,
            order_quantity=1,
            order_total_amount=201000 if pnl > 0 else 199000,
            result_price=201000 if pnl > 0 else 199000,
            result_quantity=1,
            result_total_amount=201000 if pnl > 0 else 199000,
            buy_order_id=bo.id,
            profit_loss=pnl,
            profit_rate=None,
            profit_loss_net=pnl * 0.85,
            profit_rate_net=None,
            order_placed_at=datetime(2026, 3, 22, 10, 0 + i),
            result_executed_at=datetime(2026, 3, 22, 10, 0 + i),
        )
        session.add(so)

    # 수급 열위 (bid < ask) 5건
    for i in range(5):
        d = DecisionHistory(
            stock_code="035420",
            stock_name="NAVER",
            decision="BUY",
            processing_time_ms=100,
            is_error=False,
            created_at=datetime(2026, 3, 22, 10, 30 + i),
        )
        session.add(d)
        await session.flush()

        bo = OrderHistory(
            decision_history_id=d.id,
            stock_code="035420",
            stock_name="NAVER",
            order_type="BUY",
            order_price=200000,
            order_quantity=1,
            order_total_amount=200000,
            result_price=200000,
            result_quantity=1,
            result_total_amount=200000,
            order_placed_at=datetime(2026, 3, 22, 10, 30 + i),
            result_executed_at=datetime(2026, 3, 22, 10, 30 + i),
        )
        session.add(bo)
        await session.flush()

        # 수급 열위 호가
        snap = _make_snapshot(
            stock_code="035420",
            snapshot_at=datetime(2026, 3, 22, 10, 30 + i),
            total_bid=500,
            total_ask=1000,
        )
        session.add(snap)
        await session.flush()

        # SELL: 승1패4
        pnl = 5000 if i == 0 else -3000
        so = OrderHistory(
            decision_history_id=d.id,
            stock_code="035420",
            stock_name="NAVER",
            order_type="SELL",
            order_price=201000 if pnl > 0 else 199000,
            order_quantity=1,
            order_total_amount=201000 if pnl > 0 else 199000,
            result_price=201000 if pnl > 0 else 199000,
            result_quantity=1,
            result_total_amount=201000 if pnl > 0 else 199000,
            buy_order_id=bo.id,
            profit_loss=pnl,
            profit_rate=None,
            profit_loss_net=pnl * 0.85,
            profit_rate_net=None,
            order_placed_at=datetime(2026, 3, 22, 11, 0 + i),
            result_executed_at=datetime(2026, 3, 22, 11, 0 + i),
        )
        session.add(so)

    await session.commit()

    result = await analyze_orderbook_effectiveness(session, test_date)

    assert result.supply_advantage_win_rate == pytest.approx(80.0, abs=0.1)
    assert result.supply_disadvantage_win_rate == pytest.approx(20.0, abs=0.1)
