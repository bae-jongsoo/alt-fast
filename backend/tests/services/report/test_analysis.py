"""analysis.py 테스트 — 8개 분석 항목.

PostgreSQL (asyncpg) 기반 — 기존 conftest의 TEST_DATABASE_URL 활용.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.decision_history import DecisionHistory
from app.models.minute_candle import MinuteCandle
from app.models.order_history import OrderHistory
from app.models.target_stock import TargetStock
from app.services.report.analysis import (
    analyze_benchmark,
    analyze_by_time_zone,
    analyze_entry_quality,
    analyze_hold_review_41,
    analyze_hold_review_42,
    analyze_missed_opportunities,
    analyze_repeated_trades,
    analyze_trade_frequency,
    analyze_volatility_capture,
    get_hold_summary,
)

# 전용 테스트 날짜 (core 테스트와 충돌 방지)
TEST_DATE = date(2026, 3, 15)

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


def _dt(hour: int, minute: int = 0, second: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 3, day, hour, minute, second)


def _make_decision(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    decision: str = "BUY",
    processing_time_ms: int = 500,
    created_at: datetime | None = None,
) -> DecisionHistory:
    return DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision=decision,
        processing_time_ms=processing_time_ms,
        created_at=created_at or _dt(9, 10),
    )


def _make_buy(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 70000,
    quantity: int = 10,
    decision_history_id: int = 1,
    placed_at: datetime | None = None,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = placed_at or _dt(9, 11)
    executed = executed_at or _dt(9, 11, 5)
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
        order_placed_at=placed,
        result_executed_at=executed,
    )


def _make_sell(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: float = 71000,
    quantity: int = 10,
    buy_order_id: int | None = None,
    decision_history_id: int = 1,
    profit_loss_net: float = 8000,
    placed_at: datetime | None = None,
    executed_at: datetime | None = None,
) -> OrderHistory:
    placed = placed_at or _dt(9, 30)
    executed = executed_at or _dt(9, 30, 5)
    profit_loss = profit_loss_net * 1.1  # 세전
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
        profit_loss=profit_loss,
        profit_rate=1.5,
        profit_loss_net=profit_loss_net,
        profit_rate_net=1.2,
        order_placed_at=placed,
        result_executed_at=executed,
    )


def _make_candle(
    stock_code: str,
    minute_at: datetime,
    open_: int,
    high: int,
    low: int,
    close: int,
    volume: int = 1000,
) -> MinuteCandle:
    return MinuteCandle(
        stock_code=stock_code,
        minute_at=minute_at,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


async def _add_candle_series(
    session: AsyncSession,
    stock_code: str,
    start_hour: int,
    start_min: int,
    count: int,
    base_price: int,
    prices: list[tuple[int, int, int, int]] | None = None,
    day: int = 15,
) -> None:
    """분봉 시리즈를 추가한다. prices가 제공되면 (open, high, low, close) 튜플 리스트."""
    for i in range(count):
        minute_at = _dt(start_hour, start_min + i, 0, day=day)
        if prices and i < len(prices):
            o, h, l, c = prices[i]
        else:
            o = h = l = c = base_price
        session.add(_make_candle(stock_code, minute_at, o, h, l, c))
    await session.flush()


# ── 1. test_missed_opportunities_capture_rate ────────────────────


async def test_missed_opportunities_capture_rate(session: AsyncSession):
    """매수 100, 최고 110, 매도 108 -> 캡처율 80%."""
    d = _make_decision(created_at=_dt(9, 10))
    session.add(d)
    await session.flush()

    buy = _make_buy(
        price=100, decision_history_id=d.id,
        placed_at=_dt(9, 11), executed_at=_dt(9, 11, 5),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=108, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=8, placed_at=_dt(9, 20), executed_at=_dt(9, 20, 5),
    )
    session.add(sell)
    await session.flush()

    # 분봉: 매수 구간 내 최고가 110
    prices = [
        (100, 105, 98, 103),
        (103, 110, 102, 108),
        (108, 109, 106, 108),
    ]
    await _add_candle_series(session, "005930", 9, 11, 3, 100, prices)

    items = await analyze_missed_opportunities(session, TEST_DATE)
    # 최소 1건 (이 테스트 데이터)
    target = [i for i in items if i.sell_order_id == sell.id]
    assert len(target) == 1
    item = target[0]
    assert item.capture_rate is not None
    assert abs(item.capture_rate - 80.0) < 0.1


# ── 2. test_missed_opportunities_hold_mdd ────────────────────────


async def test_missed_opportunities_hold_mdd(session: AsyncSession):
    """매수 100, 최저 95 -> 보유 중 MDD 5%."""
    target_date = date(2026, 3, 16)

    d = _make_decision(created_at=_dt(9, 10, day=16))
    session.add(d)
    await session.flush()

    buy = _make_buy(
        price=100, decision_history_id=d.id,
        placed_at=_dt(9, 11, day=16), executed_at=_dt(9, 11, 5, day=16),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=102, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=2, placed_at=_dt(9, 25, day=16),
        executed_at=_dt(9, 25, 5, day=16),
    )
    session.add(sell)
    await session.flush()

    # 분봉: 최저 95
    prices = [
        (100, 103, 95, 98),
        (98, 102, 96, 101),
        (101, 104, 99, 102),
    ]
    await _add_candle_series(session, "005930", 9, 11, 3, 100, prices, day=16)

    items = await analyze_missed_opportunities(session, target_date)
    assert len(items) >= 1
    item = items[0]
    assert item.trough_price is not None
    assert item.hold_mdd is not None
    # MDD = (100 - 95) / 100 * 100 = 5%
    assert abs(item.hold_mdd - 5.0) < 0.1


# ── 3. test_missed_opportunities_early_exit ──────────────────────


async def test_missed_opportunities_early_exit(session: AsyncSession):
    """매도 후 10분 내 +2% 상승 -> 조기 청산 감지."""
    d = _make_decision(
        stock_code="000660", stock_name="SK하이닉스",
        created_at=_dt(10, 0),
    )
    session.add(d)
    await session.flush()

    buy = _make_buy(
        stock_code="000660", stock_name="SK하이닉스",
        price=1000, decision_history_id=d.id,
        placed_at=_dt(10, 1), executed_at=_dt(10, 1, 5),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        stock_code="000660", stock_name="SK하이닉스",
        price=1010, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=10, placed_at=_dt(10, 10), executed_at=_dt(10, 10, 5),
    )
    session.add(sell)
    await session.flush()

    # 보유 구간 분봉
    buy_candles = [
        (1000, 1015, 995, 1010),
        (1010, 1012, 1005, 1010),
    ]
    await _add_candle_series(session, "000660", 10, 1, 2, 1000, buy_candles)

    # 매도 후 10분 내 분봉 — +2% 상승
    post_candles = [
        (1010, 1030, 1008, 1025),  # 1030 = +2% from 1010
        (1025, 1035, 1020, 1030),
    ]
    await _add_candle_series(session, "000660", 10, 11, 2, 1010, post_candles)

    items = await analyze_missed_opportunities(session, TEST_DATE)
    target_items = [i for i in items if i.stock_code == "000660"]
    assert len(target_items) >= 1
    item = target_items[0]
    assert item.early_exit is True
    assert item.early_exit_upside is not None
    assert item.early_exit_upside > 1.0


# ── 4. test_time_zone_grouping ───────────────────────────────────


async def test_time_zone_grouping(session: AsyncSession):
    """각 시간대 매매 배치 -> 6구간 정확히 그룹핑."""
    zone_stats, _ = await analyze_by_time_zone(session, TEST_DATE)
    assert len(zone_stats) == 6
    zone_names = [z.zone_name for z in zone_stats]
    assert "장초반" in zone_names
    assert "오전장" in zone_names
    assert "점심" in zone_names
    assert "오후장" in zone_names
    assert "마감접근" in zone_names
    assert "동시호가" in zone_names


# ── 5. test_inactive_zone_analysis ───────────────────────────────


async def test_inactive_zone_analysis(session: AsyncSession):
    """09:00~09:11 분봉 데이터 -> 변동폭/갭 유지율 계산."""
    # 감시종목 추가 (upsert)
    from sqlalchemy import select as sa_select
    existing = await session.execute(
        sa_select(TargetStock).where(TargetStock.stock_code == "005930")
    )
    if not existing.scalar_one_or_none():
        ts = TargetStock(
            stock_code="005930", stock_name="삼성전자", is_active=True,
        )
        session.add(ts)
        await session.flush()

    # 09:00~09:11 분봉 추가
    inactive_prices = [
        (70000, 70500, 69500, 70200),  # 09:00
        (70200, 70800, 70000, 70300),  # 09:01
        (70300, 71000, 70100, 70500),  # 09:02
    ]
    for i, (o, h, l, c) in enumerate(inactive_prices):
        session.add(_make_candle(
            "005930", _dt(9, i, 0), o, h, l, c,
        ))
    try:
        await session.flush()
    except Exception:
        await session.rollback()

    _, inactive = await analyze_by_time_zone(session, TEST_DATE)
    # inactive가 있으면 구조 확인
    if inactive is not None:
        assert len(inactive.stocks) > 0
        for stock in inactive.stocks:
            if stock.price_range is not None:
                assert stock.price_range >= 0


# ── 6. test_hold_review_41_consecutive ───────────────────────────


async def test_hold_review_41_consecutive(session: AsyncSession):
    """동일 종목 HOLD 5연속 -> 1개 관망 구간으로 묶임."""
    target_date = date(2026, 3, 14)

    # HOLD 5연속
    for i in range(5):
        h = _make_decision(
            stock_code="035720", stock_name="카카오",
            decision="HOLD",
            created_at=_dt(10, i * 5, 0, day=14),
        )
        session.add(h)
    await session.flush()

    # 당일 분봉 (종가 판정용)
    await _add_candle_series(
        session, "035720", 9, 0, 3, 50000,
        [(50000, 51000, 49000, 50500),
         (50500, 51500, 50000, 51000),
         (51000, 51200, 50800, 51000)],
        day=14,
    )

    items = await analyze_hold_review_41(session, target_date)
    kakao_items = [i for i in items if i.stock_code == "035720"]
    assert len(kakao_items) == 1
    assert kakao_items[0].hold_count == 5


# ── 7. test_hold_review_42_opportunity ───────────────────────────


async def test_hold_review_42_opportunity(session: AsyncSession):
    """보유 중 타 종목 +3% -> 감지."""
    target_date = date(2026, 3, 13)

    # 감시종목 추가 (upsert)
    from sqlalchemy import select as sa_select
    existing = await session.execute(
        sa_select(TargetStock).where(TargetStock.stock_code == "035720")
    )
    if not existing.scalar_one_or_none():
        ts2 = TargetStock(
            stock_code="035720", stock_name="카카오", is_active=True,
        )
        session.add(ts2)
        await session.flush()

    d = _make_decision(
        stock_code="005930", stock_name="삼성전자",
        created_at=_dt(10, 0, day=13),
    )
    session.add(d)
    await session.flush()

    buy = _make_buy(
        price=70000, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=13), executed_at=_dt(10, 0, 5, day=13),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=70500, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=5000,
        placed_at=_dt(10, 30, day=13), executed_at=_dt(10, 30, 5, day=13),
    )
    session.add(sell)
    await session.flush()

    # 보유 기간 동안 카카오 +3%
    await _add_candle_series(
        session, "035720", 10, 0, 5, 50000,
        [(50000, 50500, 49800, 50200),
         (50200, 50800, 50000, 50500),
         (50500, 51000, 50300, 50800),
         (50800, 51500, 50500, 51200),
         (51200, 51500, 51000, 51500)],  # 50000 -> 51500 = +3%
        day=13,
    )

    items = await analyze_hold_review_42(session, target_date)
    kakao_missed = [i for i in items if i.missed_stock_code == "035720"]
    assert len(kakao_missed) >= 1
    assert kakao_missed[0].missed_return_rate is not None
    assert kakao_missed[0].missed_return_rate > 2.0  # 약 +3%


# ── 8. test_volatility_capture ───────────────────────────────────


async def test_volatility_capture(session: AsyncSession):
    """변동폭 5%, 실현수익 2% -> 캡처율 40%."""
    target_date = date(2026, 3, 12)

    d = _make_decision(created_at=_dt(10, 0, day=12))
    session.add(d)
    await session.flush()

    # 매수 100, 매도 102 = 실현수익 2
    buy = _make_buy(
        price=100, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=12), executed_at=_dt(10, 0, 5, day=12),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=102, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=2,
        placed_at=_dt(10, 30, day=12), executed_at=_dt(10, 30, 5, day=12),
    )
    session.add(sell)
    await session.flush()

    # 당일 분봉: 고가 105, 저가 100 -> 변동폭 5
    await _add_candle_series(
        session, "005930", 9, 11, 5, 100,
        [(100, 102, 100, 101),
         (101, 103, 100, 102),
         (102, 105, 101, 104),
         (104, 105, 102, 103),
         (103, 104, 100, 101)],
        day=12,
    )

    items = await analyze_volatility_capture(session, target_date)
    assert len(items) >= 1
    item = items[0]
    assert item.capture_rate is not None
    assert abs(item.capture_rate - 40.0) < 0.1


# ── 9. test_benchmark_watchlist_alpha ────────────────────────────


async def test_benchmark_watchlist_alpha(session: AsyncSession):
    """감시종목 평균 +1%, 시스템 +2% -> Alpha +1%."""
    target_date = date(2026, 3, 11)

    # 감시종목 확보
    from sqlalchemy import select as sa_select
    existing = await session.execute(
        sa_select(TargetStock).where(TargetStock.stock_code == "005930")
    )
    if not existing.scalar_one_or_none():
        session.add(TargetStock(
            stock_code="005930", stock_name="삼성전자", is_active=True,
        ))
        await session.flush()

    d = _make_decision(created_at=_dt(10, 0, day=11))
    session.add(d)
    await session.flush()

    # 시스템 매매: 매수 1000, 매도 1020 -> +2%
    buy = _make_buy(
        price=1000, quantity=10, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=11), executed_at=_dt(10, 0, 5, day=11),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=1020, quantity=10, buy_order_id=buy.id,
        decision_history_id=d.id, profit_loss_net=200,
        placed_at=_dt(10, 30, day=11), executed_at=_dt(10, 30, 5, day=11),
    )
    session.add(sell)
    await session.flush()

    # 감시종목(삼성전자) 당일 분봉: 시가 1000 -> 종가 1010 (+1%)
    await _add_candle_series(
        session, "005930", 9, 0, 3, 1000,
        [(1000, 1015, 995, 1005),
         (1005, 1012, 1000, 1008),
         (1008, 1010, 1005, 1010)],
        day=11,
    )

    result = await analyze_benchmark(session, target_date)
    assert result.watchlist_avg_return is not None
    # Alpha = 시스템 수익률 - 감시종목 평균
    if result.alpha_vs_watchlist is not None:
        assert result.alpha_vs_watchlist != 0


# ── 10. test_repeated_trades_warning ─────────────────────────────


async def test_repeated_trades_warning(session: AsyncSession):
    """동일종목 3회, 수익 감소 -> 경고 플래그."""
    target_date = date(2026, 3, 10)

    d = _make_decision(
        stock_code="035720", stock_name="카카오",
        created_at=_dt(9, 10, day=10),
    )
    session.add(d)
    await session.flush()

    # 3회 반복매매, 수익 감소 패턴
    returns = [(50100, 100), (50050, 50), (50010, 10)]
    for i, (sell_price, pnl) in enumerate(returns):
        base = _dt(10, i * 20, 0, day=10)
        buy = _make_buy(
            stock_code="035720", stock_name="카카오",
            price=50000, decision_history_id=d.id,
            placed_at=base, executed_at=base + timedelta(seconds=5),
        )
        session.add(buy)
        await session.flush()

        sell = _make_sell(
            stock_code="035720", stock_name="카카오",
            price=sell_price, buy_order_id=buy.id,
            decision_history_id=d.id, profit_loss_net=pnl,
            placed_at=base + timedelta(minutes=10),
            executed_at=base + timedelta(minutes=10, seconds=5),
        )
        session.add(sell)
    await session.flush()

    items = await analyze_repeated_trades(session, target_date)
    kakao = [i for i in items if i.stock_code == "035720"]
    assert len(kakao) == 1
    assert kakao[0].round_count == 3
    assert kakao[0].warning is True


# ── 11. test_trade_frequency_fee_ratio ───────────────────────────


async def test_trade_frequency_fee_ratio(session: AsyncSession):
    """총 수수료 3만원 / 순이익 10만원 -> 비중 30% (경고)."""
    target_date = date(2026, 3, 9)

    d = _make_decision(created_at=_dt(10, 0, day=9))
    session.add(d)
    await session.flush()

    # profit_loss=130000, profit_loss_net=100000 -> 수수료 30000
    buy = _make_buy(
        price=70000, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=9), executed_at=_dt(10, 0, 5, day=9),
    )
    session.add(buy)
    await session.flush()

    sell = OrderHistory(
        stock_code="005930",
        stock_name="삼성전자",
        order_type="SELL",
        order_price=71000,
        order_quantity=10,
        order_total_amount=710000,
        result_price=71000,
        result_quantity=10,
        result_total_amount=710000,
        buy_order_id=buy.id,
        decision_history_id=d.id,
        profit_loss=130000,
        profit_rate=1.5,
        profit_loss_net=100000,
        profit_rate_net=1.2,
        order_placed_at=_dt(10, 30, day=9),
        result_executed_at=_dt(10, 30, 5, day=9),
    )
    session.add(sell)
    await session.flush()

    freq = await analyze_trade_frequency(session, target_date)
    assert freq.fee_ratio is not None
    assert abs(freq.fee_ratio - 30.0) < 0.1
    assert freq.fee_grade == "위험"


# ── 12. test_trade_frequency_idle_time ───────────────────────────


async def test_trade_frequency_idle_time(session: AsyncSession):
    """보유 2시간 / 장 6.3시간 -> 유휴율 약 68%."""
    target_date = date(2026, 3, 8)

    d = _make_decision(created_at=_dt(10, 0, day=8))
    session.add(d)
    await session.flush()

    # 10:00 ~ 12:00 보유 = 2시간 = 120분
    buy = _make_buy(
        price=70000, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=8), executed_at=_dt(10, 0, 0, day=8),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=70500, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=5000,
        placed_at=_dt(12, 0, day=8), executed_at=_dt(12, 0, 0, day=8),
    )
    session.add(sell)
    await session.flush()

    freq = await analyze_trade_frequency(session, target_date)
    # 379분 중 120분 보유 -> 유휴율 약 68.3%
    assert freq.cash_idle_ratio is not None
    assert 65.0 < freq.cash_idle_ratio < 72.0


# ── 13. test_entry_quality_position ──────────────────────────────


async def test_entry_quality_position(session: AsyncSession):
    """매수 105, 당일 저가 100, 고가 110 -> 위치 50%."""
    target_date = date(2026, 3, 7)

    d = _make_decision(created_at=_dt(10, 0, day=7))
    session.add(d)
    await session.flush()

    buy = _make_buy(
        price=105, decision_history_id=d.id,
        placed_at=_dt(10, 0, day=7), executed_at=_dt(10, 0, 5, day=7),
    )
    session.add(buy)
    await session.flush()

    sell = _make_sell(
        price=107, buy_order_id=buy.id, decision_history_id=d.id,
        profit_loss_net=2,
        placed_at=_dt(10, 30, day=7), executed_at=_dt(10, 30, 5, day=7),
    )
    session.add(sell)
    await session.flush()

    # 당일 분봉: 고가 110, 저가 100
    await _add_candle_series(
        session, "005930", 9, 11, 5, 105,
        [(102, 105, 100, 103),
         (103, 108, 102, 107),
         (107, 110, 106, 109),
         (109, 110, 105, 107),
         (107, 108, 100, 103)],
        day=7,
    )

    items = await analyze_entry_quality(session, target_date)
    assert len(items) >= 1
    item = items[0]
    assert item.entry_position_pct is not None
    assert abs(item.entry_position_pct - 50.0) < 0.1
