"""퀀트 필터 서비스 테스트."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.models.strategy import Strategy
from app.models.system_parameter import SystemParameter
from app.models.trading_event import TradingEvent
from app.services.quant_filter import (
    FilterResult,
    apply_quant_filter,
    filter_events,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession) -> Strategy:
    strategy = Strategy(
        name=f"test_strategy_{_now().timestamp()}",
        description="테스트 전략",
        initial_capital=Decimal("10000000"),
        is_active=True,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


def _make_event(
    stock_code: str,
    stock_name: str,
    strategy_id: int | None = None,
) -> TradingEvent:
    return TradingEvent(
        event_type="volume_spike",
        stock_code=stock_code,
        stock_name=stock_name,
        event_data={"spike_ratio": 3.0},
        confidence_hint=Decimal("0.50"),
        status="pending",
        strategy_id=strategy_id,
        detected_at=_now(),
    )


async def _setup_full_passing_data(
    db: AsyncSession,
    stock_code: str,
    strategy_id: int,
) -> None:
    """모든 필터를 통과하는 데이터를 준비한다."""
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # 전일 분봉: 총 거래량 1000
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=yesterday_start + timedelta(hours=9, minutes=i),
            open=50000, high=50100, low=49900, close=50000,
            volume=200,
        ))

    # 당일 분봉: 총 거래량 3000 (전일의 3배 → 2배 기준 통과)
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=today_start + timedelta(hours=9, minutes=i),
            open=50000, high=50100, low=49900, close=50000,
            volume=600,
        ))

    # 호가 스프레드: 0.2% (0.5% 이하 → 통과)
    db.add(OrderbookSnapshot(
        stock_code=stock_code,
        snapshot_at=now,
        ask_price1=50050, ask_price2=50100, ask_price3=50150,
        ask_price4=50200, ask_price5=50250,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=49950, bid_price2=49900, bid_price3=49850,
        bid_price4=49800, bid_price5=49750,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))

    # 시총: 1000억 (500억 이상 → 통과), 거래정지 아님
    db.add(MarketSnapshot(
        stock_code=stock_code,
        stock_name="테스트종목",
        external_id=f"ms_{stock_code}_{now.timestamp()}",
        published_at=now,
        hts_avls=100000000000,  # 1000억
        temp_stop_yn="N",
    ))

    await db.commit()


# ─── 거래량 필터 테스트 ───


async def test_volume_filter_below_threshold(db: AsyncSession):
    """당일 거래량이 전일의 2배 미만이면 필터링된다."""
    strategy = await _create_strategy(db)
    stock_code = "005930"
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # 전일 거래량 합계: 5000
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=yesterday_start + timedelta(hours=9, minutes=i),
            open=50000, high=50100, low=49900, close=50000,
            volume=1000,
        ))

    # 당일 거래량 합계: 3000 (전일의 0.6배 → 2배 미만)
    for i in range(3):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=today_start + timedelta(hours=9, minutes=i),
            open=50000, high=50100, low=49900, close=50000,
            volume=1000,
        ))

    # 시총, 호가, 거래정지 등은 통과하도록 설정
    db.add(MarketSnapshot(
        stock_code=stock_code, stock_name="삼성전자",
        external_id=f"ms_vol_{now.timestamp()}",
        published_at=now,
        hts_avls=100000000000, temp_stop_yn="N",
    ))
    db.add(OrderbookSnapshot(
        stock_code=stock_code, snapshot_at=now,
        ask_price1=50050, ask_price2=50100, ask_price3=50150,
        ask_price4=50200, ask_price5=50250,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=49950, bid_price2=49900, bid_price3=49850,
        bid_price4=49800, bid_price5=49750,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))
    await db.commit()

    event = _make_event(stock_code, "삼성전자", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await apply_quant_filter(db, event)

    assert result.passed is False
    assert "거래량 부족" in result.reason
    assert result.metrics["volume"]["volume_ratio"] < 2.0


# ─── 호가 스프레드 필터 테스트 ───


async def test_spread_filter_above_threshold(db: AsyncSession):
    """호가 스프레드가 0.5% 초과이면 필터링된다."""
    strategy = await _create_strategy(db)
    stock_code = "000660"
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # 거래량 필터 통과 (3배)
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=yesterday_start + timedelta(hours=9, minutes=i),
            open=100000, high=100100, low=99900, close=100000,
            volume=200,
        ))
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=today_start + timedelta(hours=9, minutes=i),
            open=100000, high=100100, low=99900, close=100000,
            volume=600,
        ))

    # 호가 스프레드: (100500 - 99500) / 100000 * 100 = 1.0% (0.5% 초과)
    db.add(OrderbookSnapshot(
        stock_code=stock_code, snapshot_at=now,
        ask_price1=100500, ask_price2=100600, ask_price3=100700,
        ask_price4=100800, ask_price5=100900,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=99500, bid_price2=99400, bid_price3=99300,
        bid_price4=99200, bid_price5=99100,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))

    db.add(MarketSnapshot(
        stock_code=stock_code, stock_name="SK하이닉스",
        external_id=f"ms_spread_{now.timestamp()}",
        published_at=now,
        hts_avls=100000000000, temp_stop_yn="N",
    ))
    await db.commit()

    event = _make_event(stock_code, "SK하이닉스", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await apply_quant_filter(db, event)

    assert result.passed is False
    assert "호가 스프레드 과다" in result.reason
    assert result.metrics["spread"]["spread_pct"] > 0.5


# ─── 시총 필터 테스트 ───


async def test_market_cap_filter_below_threshold(db: AsyncSession):
    """시가총액이 500억 미만이면 필터링된다."""
    strategy = await _create_strategy(db)
    stock_code = "035720"
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # 거래량 필터 통과
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=yesterday_start + timedelta(hours=9, minutes=i),
            open=5000, high=5100, low=4900, close=5000,
            volume=200,
        ))
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=today_start + timedelta(hours=9, minutes=i),
            open=5000, high=5100, low=4900, close=5000,
            volume=600,
        ))

    # 호가 스프레드 통과
    db.add(OrderbookSnapshot(
        stock_code=stock_code, snapshot_at=now,
        ask_price1=5010, ask_price2=5020, ask_price3=5030,
        ask_price4=5040, ask_price5=5050,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=4990, bid_price2=4980, bid_price3=4970,
        bid_price4=4960, bid_price5=4950,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))

    # 시총: 300억 (500억 미만)
    db.add(MarketSnapshot(
        stock_code=stock_code, stock_name="카카오",
        external_id=f"ms_cap_{now.timestamp()}",
        published_at=now,
        hts_avls=30000000000,  # 300억
        temp_stop_yn="N",
    ))
    await db.commit()

    event = _make_event(stock_code, "카카오", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await apply_quant_filter(db, event)

    assert result.passed is False
    assert "시총 부족" in result.reason
    assert result.metrics["market_cap"]["market_cap"] < 50000000000


# ─── 모든 조건 통과 테스트 ───


async def test_all_filters_pass(db: AsyncSession):
    """모든 필터 조건을 통과하면 passed=True."""
    strategy = await _create_strategy(db)
    stock_code = "068270"

    await _setup_full_passing_data(db, stock_code, strategy.id)

    event = _make_event(stock_code, "셀트리온", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await apply_quant_filter(db, event)

    assert result.passed is True
    assert result.reason is None
    assert "volume" in result.metrics
    assert "spread" in result.metrics
    assert "market_cap" in result.metrics
    assert "price" in result.metrics
    assert "trading_halt" in result.metrics


# ─── 기존 포지션 중복 체크 테스트 ───


async def test_existing_position_filter(db: AsyncSession):
    """해당 전략에 동일 종목 포지션이 있으면 필터링된다."""
    strategy = await _create_strategy(db)
    stock_code = "035420"

    await _setup_full_passing_data(db, stock_code, strategy.id)

    # 기존 포지션 생성
    db.add(Asset(
        strategy_id=strategy.id,
        stock_code=stock_code,
        stock_name="NAVER",
        quantity=10,
        unit_price=Decimal("300000"),
        total_amount=Decimal("3000000"),
    ))
    await db.commit()

    event = _make_event(stock_code, "NAVER", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await apply_quant_filter(db, event)

    assert result.passed is False
    assert "기존 포지션 보유" in result.reason
    assert result.metrics["position"]["existing_quantity"] == 10


# ─── 배치 필터 테스트 ───


async def test_filter_events_batch(db: AsyncSession):
    """배치 필터가 통과/필터링 이벤트를 분리하고 상태를 업데이트한다."""
    strategy = await _create_strategy(db)
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # 종목 A: 모든 필터 통과
    code_a = "006400"
    await _setup_full_passing_data(db, code_a, strategy.id)

    # 종목 B: 시총 부족으로 필터링
    code_b = "009150"
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=code_b,
            minute_at=yesterday_start + timedelta(hours=9, minutes=i),
            open=3000, high=3100, low=2900, close=3000,
            volume=200,
        ))
    for i in range(5):
        db.add(MinuteCandle(
            stock_code=code_b,
            minute_at=today_start + timedelta(hours=9, minutes=i),
            open=3000, high=3100, low=2900, close=3000,
            volume=600,
        ))
    db.add(OrderbookSnapshot(
        stock_code=code_b, snapshot_at=now,
        ask_price1=3010, ask_price2=3020, ask_price3=3030,
        ask_price4=3040, ask_price5=3050,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=2990, bid_price2=2980, bid_price3=2970,
        bid_price4=2960, bid_price5=2950,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))
    db.add(MarketSnapshot(
        stock_code=code_b, stock_name="삼성전기",
        external_id=f"ms_batch_b_{now.timestamp()}",
        published_at=now,
        hts_avls=10000000000,  # 100억 (500억 미만)
        temp_stop_yn="N",
    ))
    await db.commit()

    event_a = _make_event(code_a, "삼성SDI")
    event_b = _make_event(code_b, "삼성전기")
    db.add(event_a)
    db.add(event_b)
    await db.commit()
    await db.refresh(event_a)
    await db.refresh(event_b)

    passed, filtered = await filter_events(db, [event_a, event_b], strategy.id)

    assert len(passed) == 1
    assert len(filtered) == 1

    assert passed[0].stock_code == code_a
    assert passed[0].status == "pending"

    assert filtered[0].stock_code == code_b
    assert filtered[0].status == "filtered"
    assert filtered[0].processed_at is not None

    # event_data에 filter_result 기록 확인
    assert "filter_result" in filtered[0].event_data
    assert filtered[0].event_data["filter_result"]["passed"] is False
    assert filtered[0].event_data["filter_result"]["reason"] is not None
