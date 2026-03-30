from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.news import News
from app.models.news_cluster import NewsCluster
from app.services.param_helper import get_param

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


async def detect_news_clusters(
    db: AsyncSession,
    window_minutes: int = 60,
    min_count: int = 3,
    redis_client: aioredis.Redis | None = None,
) -> list[NewsCluster]:
    """최근 window_minutes 이내의 뉴스를 종목별로 그룹핑하여 클러스터를 생성/업데이트한다."""
    # 시스템 파라미터에서 설정 로드
    window_minutes = int(await get_param(db, "news_cluster_window_minutes", str(window_minutes)))
    min_count = int(await get_param(db, "news_cluster_min_count", str(min_count)))

    now = datetime.now(KST).replace(tzinfo=None)
    cutoff = now - timedelta(minutes=window_minutes)

    # 종목별 뉴스 건수 집계
    stmt = (
        select(
            News.stock_code,
            News.stock_name,
            func.count(News.id).label("cnt"),
            func.min(News.published_at).label("first_at"),
            func.max(News.published_at).label("last_at"),
        )
        .where(News.published_at >= cutoff)
        .group_by(News.stock_code, News.stock_name)
        .having(func.count(News.id) >= min_count)
    )
    result = await db.execute(stmt)
    groups = result.all()

    clusters: list[NewsCluster] = []
    should_close_redis = False

    for row in groups:
        stock_code = row.stock_code
        stock_name = row.stock_name
        news_count = row.cnt
        first_news_at = row.first_at
        last_news_at = row.last_at

        # 이미 존재하는 미처리 클러스터가 있는지 확인 (동일 종목, 시간 겹침)
        existing_stmt = (
            select(NewsCluster)
            .where(
                NewsCluster.stock_code == stock_code,
                NewsCluster.is_processed.is_(False),
                NewsCluster.first_news_at <= last_news_at,
                NewsCluster.last_news_at >= cutoff,
            )
            .order_by(NewsCluster.created_at.desc())
            .limit(1)
        )
        existing_result = await db.execute(existing_stmt)
        existing_cluster = existing_result.scalar_one_or_none()

        if existing_cluster:
            # 기존 클러스터 업데이트
            existing_cluster.news_count = news_count
            existing_cluster.last_news_at = last_news_at
            if first_news_at < existing_cluster.first_news_at:
                existing_cluster.first_news_at = first_news_at
            clusters.append(existing_cluster)
        else:
            # 새 클러스터 생성
            cluster = NewsCluster(
                stock_code=stock_code,
                stock_name=stock_name or "",
                cluster_type="volume",
                keyword=None,
                news_count=news_count,
                first_news_at=first_news_at,
                last_news_at=last_news_at,
                is_processed=False,
            )
            db.add(cluster)
            clusters.append(cluster)

    if clusters:
        await db.commit()

        # 새 클러스터에 대해 뉴스의 cluster_id 업데이트
        for cluster in clusters:
            await db.execute(
                update(News)
                .where(
                    News.stock_code == cluster.stock_code,
                    News.published_at >= cluster.first_news_at,
                    News.published_at <= cluster.last_news_at,
                )
                .values(cluster_id=cluster.id)
            )
        await db.commit()

        # Redis 알림
        try:
            if redis_client is None:
                redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                should_close_redis = True

            for cluster in clusters:
                await redis_client.rpush("event:news_cluster:new", str(cluster.id))

            if should_close_redis:
                await redis_client.aclose()
        except Exception:
            logger.warning("Redis 알림 실패 (클러스터 생성은 정상)", exc_info=True)

    return clusters


async def get_unprocessed_clusters(
    db: AsyncSession,
    stock_codes: list[str] | None = None,
    limit: int = 10,
) -> list[NewsCluster]:
    """미처리 클러스터 목록을 반환한다."""
    stmt = (
        select(NewsCluster)
        .where(NewsCluster.is_processed.is_(False))
        .order_by(NewsCluster.created_at.desc())
        .limit(limit)
    )
    if stock_codes:
        stmt = stmt.where(NewsCluster.stock_code.in_(stock_codes))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_cluster_processed(db: AsyncSession, cluster_id: int) -> None:
    """클러스터를 처리 완료로 표시한다."""
    await db.execute(
        update(NewsCluster)
        .where(NewsCluster.id == cluster_id)
        .values(is_processed=True)
    )
    await db.commit()
