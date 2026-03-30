"""이벤트 감지 서비스.

세 가지 이벤트 소스(DART 공시, 뉴스 클러스터, 거래량 급증)를 모니터링하고,
감지된 이벤트를 trading_events 테이블에 적재한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.minute_candle import MinuteCandle
from app.models.news_cluster import NewsCluster
from app.models.target_stock import TargetStock
from app.models.trading_event import TradingEvent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 공시 유형별 confidence_hint 매핑
_DART_CONFIDENCE: dict[str, float] = {}
_DART_KEYWORDS_HIGH = ["합병", "인수", "대규모", "계약", "M&A"]
_DART_KEYWORDS_MID = ["실적", "영업이익", "매출", "분기보고서", "사업보고서"]
_DART_KEYWORDS_LOW = ["임원", "유상증자", "무상증자", "감자", "이사"]


def _dart_confidence_hint(title: str) -> float:
    """공시 제목으로부터 confidence_hint를 결정한다."""
    title_upper = title.upper()
    for kw in _DART_KEYWORDS_HIGH:
        if kw in title_upper:
            return 0.8
    for kw in _DART_KEYWORDS_MID:
        if kw in title_upper:
            return 0.7
    for kw in _DART_KEYWORDS_LOW:
        if kw in title_upper:
            return 0.5
    return 0.3


def _news_cluster_confidence_hint(news_count: int) -> float:
    """뉴스 건수에 따른 confidence_hint를 결정한다."""
    if news_count >= 10:
        return 0.8
    if news_count >= 5:
        return 0.6
    return 0.3


def _volume_spike_confidence_hint(spike_ratio: float) -> float:
    """거래량 급증 비율에 따른 confidence_hint를 결정한다."""
    if spike_ratio >= 10:
        return 0.8
    if spike_ratio >= 5:
        return 0.6
    return 0.3


async def _find_duplicate_event(
    db: AsyncSession,
    stock_code: str,
    event_type: str,
    within_minutes: int = 10,
) -> TradingEvent | None:
    """동일 종목 + 동일 타입 + within_minutes 이내 기존 이벤트를 조회한다."""
    now = datetime.now(KST).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=within_minutes)
    stmt = (
        select(TradingEvent)
        .where(
            TradingEvent.stock_code == stock_code,
            TradingEvent.event_type == event_type,
            TradingEvent.detected_at >= cutoff,
            TradingEvent.status == "pending",
        )
        .order_by(TradingEvent.detected_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def detect_dart_events(db: AsyncSession, redis_client: aioredis.Redis | None = None) -> list[TradingEvent]:
    """미처리 DART 공시에서 이벤트를 감지한다."""
    events: list[TradingEvent] = []
    now = datetime.now(KST).replace(tzinfo=None)

    # Redis에서 먼저 시도
    disclosure_ids: list[int] = []
    if redis_client is not None:
        try:
            result = await redis_client.lpop("event:dart:new")
            while result is not None:
                try:
                    disclosure_ids.append(int(result))
                except (ValueError, TypeError):
                    pass
                result = await redis_client.lpop("event:dart:new")
        except Exception:
            logger.warning("Redis에서 DART 이벤트 읽기 실패", exc_info=True)

    # DB에서 미처리 공시 조회 (Redis에서 받은 것 + 아직 처리 안 된 것)
    if disclosure_ids:
        stmt = select(DartDisclosure).where(DartDisclosure.id.in_(disclosure_ids))
    else:
        stmt = select(DartDisclosure).where(DartDisclosure.is_processed.is_(False))
    result = await db.execute(stmt)
    disclosures = list(result.scalars().all())

    for disc in disclosures:
        # 중복 체크
        existing = await _find_duplicate_event(db, disc.stock_code, "dart_disclosure")
        if existing:
            # 기존 이벤트의 event_data 업데이트
            existing_data = existing.event_data or {}
            existing_data["title"] = disc.title
            existing.event_data = existing_data
            events.append(existing)
            continue

        confidence = _dart_confidence_hint(disc.title or "")
        event = TradingEvent(
            event_type="dart_disclosure",
            stock_code=disc.stock_code,
            stock_name=disc.stock_name or "",
            event_data={
                "disclosure_id": disc.id,
                "disclosure_type": disc.title or "",
                "title": disc.title or "",
            },
            confidence_hint=confidence,
            status="pending",
            detected_at=now,
        )
        db.add(event)
        events.append(event)

    if events:
        await db.commit()

    return events


async def detect_news_cluster_events(db: AsyncSession, redis_client: aioredis.Redis | None = None) -> list[TradingEvent]:
    """미처리 뉴스 클러스터에서 이벤트를 감지한다."""
    events: list[TradingEvent] = []
    now = datetime.now(KST).replace(tzinfo=None)

    # Redis에서 먼저 시도
    cluster_ids: list[int] = []
    if redis_client is not None:
        try:
            result = await redis_client.lpop("event:news_cluster:new")
            while result is not None:
                try:
                    cluster_ids.append(int(result))
                except (ValueError, TypeError):
                    pass
                result = await redis_client.lpop("event:news_cluster:new")
        except Exception:
            logger.warning("Redis에서 뉴스 클러스터 이벤트 읽기 실패", exc_info=True)

    # DB에서 미처리 클러스터 조회
    if cluster_ids:
        stmt = select(NewsCluster).where(NewsCluster.id.in_(cluster_ids))
    else:
        stmt = select(NewsCluster).where(NewsCluster.is_processed.is_(False))
    result = await db.execute(stmt)
    clusters = list(result.scalars().all())

    for cluster in clusters:
        # 중복 체크
        existing = await _find_duplicate_event(db, cluster.stock_code, "news_cluster")
        if existing:
            existing_data = existing.event_data or {}
            existing_data["news_count"] = cluster.news_count
            existing.event_data = existing_data
            existing.confidence_hint = _news_cluster_confidence_hint(cluster.news_count)
            events.append(existing)
            continue

        confidence = _news_cluster_confidence_hint(cluster.news_count)
        event = TradingEvent(
            event_type="news_cluster",
            stock_code=cluster.stock_code,
            stock_name=cluster.stock_name,
            event_data={
                "cluster_id": cluster.id,
                "news_count": cluster.news_count,
                "keyword": cluster.keyword,
            },
            confidence_hint=confidence,
            status="pending",
            detected_at=now,
        )
        db.add(event)
        events.append(event)

    if events:
        await db.commit()

    return events


async def detect_volume_spike_events(
    db: AsyncSession,
    redis_client: aioredis.Redis | None = None,
    spike_threshold: float = 2.0,
) -> list[TradingEvent]:
    """거래량 급증을 감지하여 이벤트를 생성한다.

    Redis에서 최근 분봉 데이터를 조회하고,
    전일 동시간대 평균 거래량과 비교하여 급증을 판단한다.
    """
    events: list[TradingEvent] = []
    now = datetime.now(KST).replace(tzinfo=None)

    # 타겟 종목 조회
    stmt = select(TargetStock).where(TargetStock.is_active.is_(True))
    result = await db.execute(stmt)
    target_stocks = list(result.scalars().all())

    for ts in target_stocks:
        stock_code = ts.stock_code
        stock_name = ts.stock_name

        # Redis에서 최근 5분간 거래량 조회
        current_volume = 0
        if redis_client is not None:
            try:
                key = f"ws:trade:{stock_code}"
                now_ts = datetime.now(KST).timestamp()
                five_min_ago_ts = now_ts - 300  # 5분 = 300초
                # sorted set에서 최근 5분 데이터 조회
                raw_ticks = await redis_client.zrangebyscore(key, five_min_ago_ts, now_ts)
                for raw in raw_ticks:
                    try:
                        tick = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                        current_volume += int(tick.get("volume", 0))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue
            except Exception:
                logger.warning(f"Redis에서 {stock_code} 거래량 조회 실패", exc_info=True)
                continue

        if current_volume <= 0:
            continue

        # 전일 동시간대 평균 거래량 (DB MinuteCandle 기반)
        yesterday = now - timedelta(days=1)
        current_hour = now.hour
        current_minute = now.minute
        # 전일 동시간대 +/- 30분 범위의 분봉
        yesterday_start = yesterday.replace(hour=max(0, current_hour - 1), minute=0, second=0, microsecond=0)
        yesterday_end = yesterday.replace(hour=min(23, current_hour + 1), minute=59, second=59, microsecond=0)

        avg_stmt = (
            select(func.avg(MinuteCandle.volume))
            .where(
                MinuteCandle.stock_code == stock_code,
                MinuteCandle.minute_at >= yesterday_start,
                MinuteCandle.minute_at <= yesterday_end,
            )
        )
        avg_result = await db.execute(avg_stmt)
        avg_volume_raw = avg_result.scalar_one_or_none()
        avg_volume = float(avg_volume_raw) if avg_volume_raw else 0

        if avg_volume <= 0:
            continue

        spike_ratio = current_volume / avg_volume

        if spike_ratio < spike_threshold:
            continue

        # 중복 체크
        existing = await _find_duplicate_event(db, stock_code, "volume_spike")
        if existing:
            existing_data = existing.event_data or {}
            existing_data["current_volume"] = current_volume
            existing_data["spike_ratio"] = round(spike_ratio, 2)
            existing.event_data = existing_data
            existing.confidence_hint = _volume_spike_confidence_hint(spike_ratio)
            events.append(existing)
            continue

        confidence = _volume_spike_confidence_hint(spike_ratio)
        event = TradingEvent(
            event_type="volume_spike",
            stock_code=stock_code,
            stock_name=stock_name,
            event_data={
                "current_volume": current_volume,
                "avg_volume": round(avg_volume, 2),
                "spike_ratio": round(spike_ratio, 2),
            },
            confidence_hint=confidence,
            status="pending",
            detected_at=now,
        )
        db.add(event)
        events.append(event)

    if events:
        await db.commit()

    return events


# ─── 이벤트 조회 헬퍼 ───


async def get_pending_events(
    db: AsyncSession,
    strategy_id: int | None = None,
    limit: int = 10,
) -> list[TradingEvent]:
    """미처리(pending) 이벤트를 조회한다."""
    stmt = (
        select(TradingEvent)
        .where(TradingEvent.status == "pending")
        .order_by(TradingEvent.detected_at.desc())
        .limit(limit)
    )
    if strategy_id is not None:
        stmt = stmt.where(TradingEvent.strategy_id == strategy_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_event_status(
    db: AsyncSession,
    event_id: int,
    status: str,
    decision_history_id: int | None = None,
) -> None:
    """이벤트 상태를 변경한다."""
    values: dict = {"status": status}
    if status in ("decided", "sent_to_llm", "filtered"):
        values["processed_at"] = datetime.now(KST).replace(tzinfo=None)
    if decision_history_id is not None:
        values["decision_history_id"] = decision_history_id
    await db.execute(
        update(TradingEvent)
        .where(TradingEvent.id == event_id)
        .values(**values)
    )
    await db.commit()


async def expire_old_events(db: AsyncSession, max_age_hours: int = 4) -> int:
    """장중 미처리 이벤트를 만료 처리한다. 반환: 만료 처리된 이벤트 수."""
    now = datetime.now(KST).replace(tzinfo=None)
    cutoff = now - timedelta(hours=max_age_hours)
    result = await db.execute(
        update(TradingEvent)
        .where(
            TradingEvent.status == "pending",
            TradingEvent.detected_at < cutoff,
        )
        .values(status="expired", processed_at=now)
    )
    await db.commit()
    return result.rowcount


# ─── 통합 이벤트 루프 ───


async def run_event_detection_loop(
    db: AsyncSession,
    redis_client: aioredis.Redis | None = None,
    interval_seconds: int = 30,
) -> None:
    """30초 간격으로 세 가지 감지 함수를 병렬 실행한다."""
    while True:
        try:
            results = await asyncio.gather(
                detect_dart_events(db, redis_client),
                detect_news_cluster_events(db, redis_client),
                detect_volume_spike_events(db, redis_client),
                return_exceptions=True,
            )
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.error(f"이벤트 감지 실패 (source={i}): {r}", exc_info=r)
                elif r:
                    source_name = ["dart", "news_cluster", "volume_spike"][i]
                    logger.info(f"이벤트 감지: {source_name} {len(r)}건")

            # 오래된 이벤트 만료
            expired = await expire_old_events(db)
            if expired:
                logger.info(f"만료 이벤트 {expired}건 처리")

        except Exception:
            logger.error("이벤트 감지 루프 오류", exc_info=True)

        await asyncio.sleep(interval_seconds)
