"""이벤트 감지 서비스 테스트."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.minute_candle import MinuteCandle
from app.models.news_cluster import NewsCluster
from app.models.strategy import Strategy
from app.models.target_stock import TargetStock
from app.models.trading_event import TradingEvent
from app.services.event_detector import (
    detect_dart_events,
    detect_news_cluster_events,
    detect_volume_spike_events,
    expire_old_events,
    get_pending_events,
    update_event_status,
    _dart_confidence_hint,
    _news_cluster_confidence_hint,
    _volume_spike_confidence_hint,
    _find_duplicate_event,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def _make_disclosure(
    stock_code: str,
    stock_name: str,
    title: str,
    idx: int = 0,
    is_processed: bool = False,
) -> DartDisclosure:
    return DartDisclosure(
        stock_code=stock_code,
        stock_name=stock_name,
        external_id=f"dart_{stock_code}_{title}_{idx}",
        corp_code=f"corp_{stock_code}",
        rcept_no=f"rcept_{idx}",
        title=title,
        link=f"https://dart.fss.or.kr/{idx}",
        is_processed=is_processed,
    )


def _make_news_cluster(
    stock_code: str,
    stock_name: str,
    news_count: int,
    is_processed: bool = False,
    keyword: str | None = None,
) -> NewsCluster:
    now = _now()
    return NewsCluster(
        stock_code=stock_code,
        stock_name=stock_name,
        cluster_type="volume",
        keyword=keyword,
        news_count=news_count,
        first_news_at=now - timedelta(minutes=30),
        last_news_at=now,
        is_processed=is_processed,
    )


async def _create_strategy(db: AsyncSession) -> Strategy:
    """테스트용 전략 생성."""
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


# ─── 공시 이벤트 감지 테스트 ───


async def test_detect_dart_events_creates_events(db: AsyncSession):
    """미처리 공시에서 TradingEvent가 생성된다."""
    db.add(_make_disclosure("005930", "삼성전자", "합병 관련 공시", idx=1))
    db.add(_make_disclosure("000660", "SK하이닉스", "실적 공시", idx=2))
    await db.commit()

    events = await detect_dart_events(db)

    assert len(events) == 2
    samsung_event = next(e for e in events if e.stock_code == "005930")
    assert samsung_event.event_type == "dart_disclosure"
    assert samsung_event.status == "pending"
    assert float(samsung_event.confidence_hint) == 0.8  # 합병 → 0.8
    assert samsung_event.event_data["title"] == "합병 관련 공시"

    sk_event = next(e for e in events if e.stock_code == "000660")
    assert float(sk_event.confidence_hint) == 0.7  # 실적 → 0.7


async def test_detect_dart_events_no_unprocessed(db: AsyncSession):
    """모든 공시가 처리 완료이면 이벤트가 생성되지 않는다."""
    db.add(_make_disclosure("005930", "삼성전자", "기타 공시", idx=3, is_processed=True))
    await db.commit()

    events = await detect_dart_events(db)
    assert len(events) == 0


async def test_dart_confidence_hint_values():
    """공시 유형별 confidence_hint 값 검증."""
    assert _dart_confidence_hint("합병 관련 공시") == 0.8
    assert _dart_confidence_hint("대규모 계약 체결") == 0.8
    assert _dart_confidence_hint("실적 공시") == 0.7
    assert _dart_confidence_hint("임원 변경") == 0.5
    assert _dart_confidence_hint("기타 공시 내용") == 0.3


# ─── 뉴스 클러스터 이벤트 감지 테스트 ───


async def test_detect_news_cluster_events(db: AsyncSession):
    """미처리 뉴스 클러스터에서 TradingEvent가 생성된다."""
    db.add(_make_news_cluster("005930", "삼성전자", news_count=5))
    db.add(_make_news_cluster("000660", "SK하이닉스", news_count=12))
    await db.commit()

    events = await detect_news_cluster_events(db)

    assert len(events) == 2
    samsung_event = next(e for e in events if e.stock_code == "005930")
    assert samsung_event.event_type == "news_cluster"
    assert float(samsung_event.confidence_hint) == 0.6  # 5건 → 0.6

    sk_event = next(e for e in events if e.stock_code == "000660")
    assert float(sk_event.confidence_hint) == 0.8  # 12건 → 0.8
    assert sk_event.event_data["news_count"] == 12


async def test_detect_news_cluster_no_unprocessed(db: AsyncSession):
    """미처리 클러스터가 없으면 이벤트가 생성되지 않는다."""
    db.add(_make_news_cluster("005930", "삼성전자", news_count=5, is_processed=True))
    await db.commit()

    events = await detect_news_cluster_events(db)
    assert len(events) == 0


async def test_news_cluster_confidence_hint():
    """뉴스 건수별 confidence_hint 값 검증."""
    assert _news_cluster_confidence_hint(3) == 0.3
    assert _news_cluster_confidence_hint(5) == 0.6
    assert _news_cluster_confidence_hint(10) == 0.8
    assert _news_cluster_confidence_hint(15) == 0.8


# ─── 거래량 급증 감지 테스트 ───


async def test_detect_volume_spike_events(db: AsyncSession):
    """분봉 데이터 기반으로 거래량 급증 이벤트가 생성된다."""
    strategy = await _create_strategy(db)
    ts = TargetStock(
        strategy_id=strategy.id,
        stock_code="005930",
        stock_name="삼성전자",
        is_active=True,
    )
    db.add(ts)

    # 전일 동시간대 분봉 데이터 (평균 거래량 = 1000)
    now = _now()
    yesterday = now - timedelta(days=1)
    for i in range(5):
        minute_at = yesterday.replace(
            hour=now.hour, minute=max(0, now.minute - 2 + i), second=0, microsecond=0
        )
        db.add(MinuteCandle(
            stock_code="005930",
            minute_at=minute_at,
            open=50000,
            high=50100,
            low=49900,
            close=50050,
            volume=1000,
        ))
    await db.commit()

    # Redis mock: 최근 5분간 거래량 합계 = 5000 (평균 1000 대비 5배)
    now_ts = datetime.now(KST).timestamp()
    mock_redis = AsyncMock()
    tick_data = json.dumps({"volume": 5000})
    mock_redis.zrangebyscore = AsyncMock(return_value=[tick_data])
    mock_redis.lpop = AsyncMock(return_value=None)

    events = await detect_volume_spike_events(db, redis_client=mock_redis, spike_threshold=2.0)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "volume_spike"
    assert event.stock_code == "005930"
    assert event.event_data["current_volume"] == 5000
    assert event.event_data["spike_ratio"] >= 2.0
    assert float(event.confidence_hint) == 0.6  # 5x → 0.6


async def test_detect_volume_spike_below_threshold(db: AsyncSession):
    """급증 임계값 미만이면 이벤트가 생성되지 않는다."""
    strategy = await _create_strategy(db)
    ts = TargetStock(
        strategy_id=strategy.id,
        stock_code="000660",
        stock_name="SK하이닉스",
        is_active=True,
    )
    db.add(ts)

    now = _now()
    yesterday = now - timedelta(days=1)
    for i in range(5):
        minute_at = yesterday.replace(
            hour=now.hour, minute=max(0, now.minute - 2 + i), second=0, microsecond=0
        )
        db.add(MinuteCandle(
            stock_code="000660",
            minute_at=minute_at,
            open=100000,
            high=100100,
            low=99900,
            close=100050,
            volume=1000,
        ))
    await db.commit()

    # 거래량 1500: 1.5배 → 임계값(2.0) 미만
    mock_redis = AsyncMock()
    tick_data = json.dumps({"volume": 1500})
    mock_redis.zrangebyscore = AsyncMock(return_value=[tick_data])
    mock_redis.lpop = AsyncMock(return_value=None)

    events = await detect_volume_spike_events(db, redis_client=mock_redis, spike_threshold=2.0)
    assert len(events) == 0


async def test_volume_spike_confidence_hint():
    """거래량 급증 비율별 confidence_hint 값 검증."""
    assert _volume_spike_confidence_hint(2.0) == 0.3
    assert _volume_spike_confidence_hint(5.0) == 0.6
    assert _volume_spike_confidence_hint(10.0) == 0.8
    assert _volume_spike_confidence_hint(15.0) == 0.8


# ─── 중복 이벤트 필터링 테스트 ───


async def test_duplicate_event_filtering(db: AsyncSession):
    """동일 종목 + 동일 타입 + 10분 이내 이벤트는 중복으로 처리된다."""
    now = _now()

    # 첫 번째 공시 → 이벤트 생성
    db.add(_make_disclosure("005930", "삼성전자", "합병 관련 공시 1", idx=10))
    await db.commit()

    events1 = await detect_dart_events(db)
    assert len(events1) == 1
    first_event_id = events1[0].id

    # 두 번째 공시 추가 (10분 이내)
    db.add(_make_disclosure("005930", "삼성전자", "합병 관련 공시 2", idx=11))
    await db.commit()

    events2 = await detect_dart_events(db)
    # 중복이므로 기존 이벤트가 업데이트됨
    assert len(events2) >= 1
    # 기존 이벤트 ID가 포함되어 있어야 함
    event_ids = [e.id for e in events2]
    assert first_event_id in event_ids


# ─── 이벤트 상태 변경 및 만료 테스트 ───


async def test_update_event_status(db: AsyncSession):
    """이벤트 상태 변경이 정상 동작한다."""
    event = TradingEvent(
        event_type="dart_disclosure",
        stock_code="005930",
        stock_name="삼성전자",
        event_data={"title": "테스트"},
        confidence_hint=0.5,
        status="pending",
        detected_at=_now(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    await update_event_status(db, event.id, "sent_to_llm")
    await db.refresh(event)

    assert event.status == "sent_to_llm"
    assert event.processed_at is not None


async def test_update_event_status_with_decision(db: AsyncSession):
    """이벤트 상태 변경 시 decision_history_id가 설정된다."""
    # decision_history FK를 위해 전략과 판단 이력 생성
    strategy = await _create_strategy(db)
    decision = DecisionHistory(
        strategy_id=strategy.id,
        stock_code="005930",
        stock_name="삼성전자",
        decision="BUY",
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)

    event = TradingEvent(
        event_type="news_cluster",
        stock_code="005930",
        stock_name="삼성전자",
        event_data={"cluster_id": 1},
        confidence_hint=0.6,
        status="pending",
        detected_at=_now(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    await update_event_status(db, event.id, "decided", decision_history_id=decision.id)
    await db.refresh(event)

    assert event.status == "decided"
    assert event.decision_history_id == decision.id


async def test_expire_old_events(db: AsyncSession):
    """오래된 pending 이벤트가 expired 상태로 변경된다."""
    now = _now()

    # 5시간 전 이벤트 (만료 대상)
    old_event = TradingEvent(
        event_type="dart_disclosure",
        stock_code="005930",
        stock_name="삼성전자",
        event_data={"title": "오래된 공시"},
        confidence_hint=0.3,
        status="pending",
        detected_at=now - timedelta(hours=5),
    )
    # 최근 이벤트 (만료 대상 아님)
    recent_event = TradingEvent(
        event_type="dart_disclosure",
        stock_code="000660",
        stock_name="SK하이닉스",
        event_data={"title": "최근 공시"},
        confidence_hint=0.3,
        status="pending",
        detected_at=now - timedelta(minutes=30),
    )
    db.add(old_event)
    db.add(recent_event)
    await db.commit()
    await db.refresh(old_event)
    await db.refresh(recent_event)

    expired_count = await expire_old_events(db, max_age_hours=4)

    assert expired_count >= 1

    await db.refresh(old_event)
    await db.refresh(recent_event)

    assert old_event.status == "expired"
    assert old_event.processed_at is not None
    assert recent_event.status == "pending"


async def test_get_pending_events(db: AsyncSession):
    """pending 상태의 이벤트만 조회된다."""
    now = _now()

    # pending 이벤트
    pending = TradingEvent(
        event_type="volume_spike",
        stock_code="005930",
        stock_name="삼성전자",
        event_data={"spike_ratio": 3.0},
        confidence_hint=0.3,
        status="pending",
        detected_at=now,
    )
    # decided 이벤트
    decided = TradingEvent(
        event_type="dart_disclosure",
        stock_code="000660",
        stock_name="SK하이닉스",
        event_data={"title": "결정됨"},
        confidence_hint=0.5,
        status="decided",
        detected_at=now,
        processed_at=now,
    )
    db.add(pending)
    db.add(decided)
    await db.commit()

    events = await get_pending_events(db)

    # pending 이벤트만 포함되어야 함
    statuses = {e.status for e in events}
    assert "decided" not in statuses
    assert all(e.status == "pending" for e in events)
