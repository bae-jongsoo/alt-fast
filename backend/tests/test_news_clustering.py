"""뉴스 클러스터링 서비스 테스트."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import News
from app.models.news_cluster import NewsCluster
from app.services.news_clustering import (
    detect_news_clusters,
    get_unprocessed_clusters,
    mark_cluster_processed,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def _make_news(stock_code: str, stock_name: str, title: str, minutes_ago: int = 0) -> News:
    """테스트용 뉴스 레코드 생성."""
    published = _now() - timedelta(minutes=minutes_ago)
    return News(
        stock_code=stock_code,
        stock_name=stock_name,
        external_id=f"{stock_code}_{title}_{minutes_ago}",
        link=f"https://example.com/{stock_code}/{title}",
        title=title,
        published_at=published,
    )


async def test_cluster_created_when_min_count_reached(db: AsyncSession):
    """동일 종목 뉴스가 min_count 이상이면 클러스터가 생성된다."""
    # 삼성전자 뉴스 3건 (기본 min_count=3)
    for i in range(3):
        db.add(_make_news("005930", "삼성전자", f"뉴스{i}", minutes_ago=i * 5))
    await db.commit()

    clusters = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.stock_code == "005930"
    assert cluster.stock_name == "삼성전자"
    assert cluster.cluster_type == "volume"
    assert cluster.news_count == 3
    assert cluster.is_processed is False


async def test_no_cluster_when_below_min_count(db: AsyncSession):
    """min_count 미만이면 클러스터가 생성되지 않는다."""
    # 뉴스 2건만 추가
    for i in range(2):
        db.add(_make_news("000660", "SK하이닉스", f"뉴스{i}", minutes_ago=i * 5))
    await db.commit()

    clusters = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)
    assert len(clusters) == 0


async def test_news_outside_window_excluded(db: AsyncSession):
    """시간 윈도우 밖의 뉴스는 클러스터에 포함되지 않는다."""
    # 2건은 최근, 1건은 윈도우 밖 (120분 전)
    db.add(_make_news("005930", "삼성전자", "최근뉴스1", minutes_ago=5))
    db.add(_make_news("005930", "삼성전자", "최근뉴스2", minutes_ago=10))
    db.add(_make_news("005930", "삼성전자", "오래된뉴스", minutes_ago=120))
    await db.commit()

    clusters = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)
    assert len(clusters) == 0


async def test_existing_cluster_updated(db: AsyncSession):
    """기존 미처리 클러스터가 있으면 업데이트한다 (중복 생성 방지)."""
    # 먼저 3건으로 클러스터 생성
    for i in range(3):
        db.add(_make_news("005930", "삼성전자", f"1차뉴스{i}", minutes_ago=30 - i * 5))
    await db.commit()

    clusters1 = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)
    assert len(clusters1) == 1
    cluster_id = clusters1[0].id
    original_count = clusters1[0].news_count

    # 추가 뉴스 1건 더 추가 → 총 4건
    db.add(_make_news("005930", "삼성전자", "추가뉴스", minutes_ago=2))
    await db.commit()

    clusters2 = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)
    assert len(clusters2) == 1
    # 같은 클러스터가 업데이트됨
    assert clusters2[0].id == cluster_id
    assert clusters2[0].news_count == original_count + 1


async def test_get_unprocessed_clusters(db: AsyncSession):
    """미처리 클러스터 조회."""
    # 클러스터 생성을 위한 뉴스 추가
    for i in range(3):
        db.add(_make_news("005930", "삼성전자", f"테스트뉴스{i}", minutes_ago=i * 5))
    await db.commit()

    await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)

    unprocessed = await get_unprocessed_clusters(db)
    assert len(unprocessed) >= 1
    assert all(c.is_processed is False for c in unprocessed)


async def test_mark_cluster_processed(db: AsyncSession):
    """클러스터 처리 완료 표시."""
    for i in range(3):
        db.add(_make_news("005930", "삼성전자", f"처리뉴스{i}", minutes_ago=i * 5))
    await db.commit()

    clusters = await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)
    assert len(clusters) >= 1
    cluster_id = clusters[0].id

    await mark_cluster_processed(db, cluster_id)

    # 미처리 목록에서 사라졌는지 확인
    unprocessed = await get_unprocessed_clusters(db)
    processed_ids = [c.id for c in unprocessed]
    assert cluster_id not in processed_ids


async def test_get_unprocessed_clusters_with_stock_filter(db: AsyncSession):
    """종목 코드 필터로 미처리 클러스터 조회."""
    # 삼성전자 뉴스 3건
    for i in range(3):
        db.add(_make_news("005930", "삼성전자", f"삼성뉴스{i}", minutes_ago=i * 5))
    # SK하이닉스 뉴스 3건
    for i in range(3):
        db.add(_make_news("000660", "SK하이닉스", f"하이닉스뉴스{i}", minutes_ago=i * 5))
    await db.commit()

    await detect_news_clusters(db, window_minutes=60, min_count=3, redis_client=None)

    # 삼성전자만 필터
    filtered = await get_unprocessed_clusters(db, stock_codes=["005930"])
    assert all(c.stock_code == "005930" for c in filtered)
    assert len(filtered) >= 1
