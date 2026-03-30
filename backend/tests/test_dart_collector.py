"""DART 공시 수집 관련 테스트."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.strategy import Strategy
from app.models.target_stock import TargetStock
from app.services.dart_collector import (
    collect_dart,
    get_unprocessed_disclosures,
    mark_disclosure_processed,
    upsert_disclosures,
)


# ── Helpers ──────────────────────────────────────────────────────


async def _create_strategy(db: AsyncSession) -> Strategy:
    strategy = Strategy(name="test_strategy", initial_capital=Decimal("10000000"))
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_target_stock(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str = "005930",
    dart_corp_code: str = "00126380",
) -> TargetStock:
    ts = TargetStock(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name="삼성전자",
        dart_corp_code=dart_corp_code,
        is_active=True,
    )
    db.add(ts)
    await db.commit()
    await db.refresh(ts)
    return ts


def _make_row(rcept_no: str = "20260329000001", title: str = "테스트 공시") -> dict:
    return {
        "rcept_no": rcept_no,
        "title": title,
        "link": "https://dart.fss.or.kr/test",
        "description": "공시 설명",
        "rcept_dt": "20260329",
    }


# ── Tests: is_processed 플래그 ───────────────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_new_disclosure_has_is_processed_false(db: AsyncSession):
    """신규 공시 생성 시 is_processed=False."""
    saved, new_ids = await upsert_disclosures(
        db,
        stock_code="005930",
        corp_code="00126380",
        rows=[_make_row()],
    )
    assert len(saved) == 1
    assert saved[0].is_processed is False
    assert len(new_ids) == 1
    assert new_ids[0] == saved[0].id


@pytest.mark.asyncio(loop_scope="session")
async def test_mark_disclosure_processed(db: AsyncSession):
    """mark_disclosure_processed 호출 후 is_processed=True."""
    saved, new_ids = await upsert_disclosures(
        db,
        stock_code="005930",
        corp_code="00126380",
        rows=[_make_row(rcept_no="20260329000002")],
    )
    disclosure = saved[0]
    assert disclosure.is_processed is False

    await mark_disclosure_processed(db, disclosure.id)

    result = await db.execute(
        select(DartDisclosure).where(DartDisclosure.id == disclosure.id)
    )
    updated = result.scalar_one()
    assert updated.is_processed is True


# ── Tests: get_unprocessed_disclosures ──────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_get_unprocessed_disclosures_returns_only_unprocessed(db: AsyncSession):
    """get_unprocessed_disclosures는 is_processed=False인 것만 반환."""
    # 미처리 공시 2건 생성
    saved1, _ = await upsert_disclosures(
        db, stock_code="005930", corp_code="00126380",
        rows=[_make_row(rcept_no="20260329000010", title="미처리1")],
    )
    saved2, _ = await upsert_disclosures(
        db, stock_code="005930", corp_code="00126380",
        rows=[_make_row(rcept_no="20260329000011", title="미처리2")],
    )

    # 1건 처리 완료 처리
    await mark_disclosure_processed(db, saved1[0].id)

    unprocessed = await get_unprocessed_disclosures(db)
    unprocessed_ids = {d.id for d in unprocessed}

    assert saved1[0].id not in unprocessed_ids
    assert saved2[0].id in unprocessed_ids


@pytest.mark.asyncio(loop_scope="session")
async def test_get_unprocessed_disclosures_filter_by_stock_codes(db: AsyncSession):
    """stock_codes 필터로 특정 종목만 조회."""
    await upsert_disclosures(
        db, stock_code="005930", corp_code="00126380",
        rows=[_make_row(rcept_no="20260329000020", title="삼성 공시")],
    )
    await upsert_disclosures(
        db, stock_code="000660", corp_code="00164779",
        rows=[_make_row(rcept_no="20260329000021", title="하이닉스 공시")],
    )

    # 삼성전자만 필터
    result = await get_unprocessed_disclosures(db, stock_codes=["005930"])
    stock_codes = {d.stock_code for d in result}
    assert "005930" in stock_codes
    assert "000660" not in stock_codes


@pytest.mark.asyncio(loop_scope="session")
async def test_get_unprocessed_disclosures_respects_limit(db: AsyncSession):
    """limit 파라미터가 올바르게 동작."""
    for i in range(5):
        await upsert_disclosures(
            db, stock_code="005930", corp_code="00126380",
            rows=[_make_row(rcept_no=f"2026032900003{i}", title=f"공시{i}")],
        )

    result = await get_unprocessed_disclosures(db, limit=2)
    assert len(result) == 2


# ── Tests: 수집 시 Redis 알림 ────────────────────────────────────


@pytest.mark.asyncio(loop_scope="session")
async def test_collect_dart_sends_redis_notification(db: AsyncSession):
    """신규 공시 수집 시 Redis에 알림을 보낸다."""
    strategy = await _create_strategy(db)
    await _create_target_stock(db, strategy.id)

    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.aclose = AsyncMock()

    fake_rows = [_make_row(rcept_no="20260329000040", title="Redis 테스트 공시")]

    with patch(
        "app.services.dart_collector.fetch_disclosures",
        return_value=fake_rows,
    ):
        result = await collect_dart(db, redis_client=mock_redis)

    assert result["new_items"] >= 1
    mock_redis.rpush.assert_called_once()
    call_args = mock_redis.rpush.call_args
    assert call_args[0][0] == "event:dart:new"


@pytest.mark.asyncio(loop_scope="session")
async def test_collect_dart_no_redis_notification_for_existing(db: AsyncSession):
    """기존 공시만 있으면 Redis 알림을 보내지 않는다."""
    strategy = await _create_strategy(db)
    await _create_target_stock(db, strategy.id, stock_code="000660", dart_corp_code="00164779")

    fake_rows = [_make_row(rcept_no="20260329000050", title="기존 공시")]

    # 먼저 한번 수집
    with patch(
        "app.services.dart_collector.fetch_disclosures",
        return_value=fake_rows,
    ):
        await collect_dart(db)

    # 두 번째 수집 — 같은 데이터이므로 신규 없음
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch(
        "app.services.dart_collector.fetch_disclosures",
        return_value=fake_rows,
    ):
        result = await collect_dart(db, redis_client=mock_redis)

    assert result["new_items"] == 0
    mock_redis.rpush.assert_not_called()


@pytest.mark.asyncio(loop_scope="session")
async def test_upsert_existing_disclosure_not_in_new_ids(db: AsyncSession):
    """기존 공시를 다시 upsert하면 new_ids에 포함되지 않는다."""
    rows = [_make_row(rcept_no="20260329000060")]

    saved1, new_ids1 = await upsert_disclosures(
        db, stock_code="005930", corp_code="00126380", rows=rows,
    )
    assert len(new_ids1) == 1

    # 같은 데이터로 다시 upsert
    saved2, new_ids2 = await upsert_disclosures(
        db, stock_code="005930", corp_code="00126380", rows=rows,
    )
    assert len(new_ids2) == 0
    assert len(saved2) == 1
