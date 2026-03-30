"""히스토리컬 데이터 백필 테스트."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_snapshot import MacroSnapshot
from app.models.system_parameter import SystemParameter
from app.shared.macro_api import MacroData


# ── backfill_macro() 테스트 ────────────────────────────────────────


async def test_backfill_macro_inserts_data(db: AsyncSession):
    """backfill_macro()가 기간별 데이터를 DB에 적재하는지 확인."""
    mock_macro_list = [
        MacroData(
            snapshot_date=date(2026, 3, 1),
            sp500_close=5800.0,
            sp500_change_pct=1.0,
            nasdaq_close=18000.0,
            usd_krw=1350.0,
        ),
        MacroData(
            snapshot_date=date(2026, 3, 2),
            sp500_close=5820.0,
            sp500_change_pct=0.34,
            nasdaq_close=18100.0,
            usd_krw=1348.0,
        ),
        MacroData(
            snapshot_date=date(2026, 3, 3),
            sp500_close=5810.0,
            sp500_change_pct=-0.17,
            nasdaq_close=18050.0,
            usd_krw=1352.0,
        ),
    ]

    with patch(
        "app.services.macro_collector.fetch_macro_data_range",
        return_value=mock_macro_list,
    ):
        from app.services.macro_collector import backfill_macro

        result = await backfill_macro(
            db,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 3),
        )

    assert result["inserted"] == 3
    assert result["updated"] == 0
    assert result["skipped"] == 0

    # DB에서 확인
    rows = await db.execute(
        select(MacroSnapshot)
        .where(
            MacroSnapshot.snapshot_date >= date(2026, 3, 1),
            MacroSnapshot.snapshot_date <= date(2026, 3, 3),
        )
        .order_by(MacroSnapshot.snapshot_date)
    )
    snapshots = rows.scalars().all()
    assert len(snapshots) == 3
    assert float(snapshots[0].sp500_close) == pytest.approx(5800.0, abs=0.01)
    assert float(snapshots[1].sp500_close) == pytest.approx(5820.0, abs=0.01)
    assert float(snapshots[2].sp500_close) == pytest.approx(5810.0, abs=0.01)


async def test_backfill_macro_skips_existing(db: AsyncSession):
    """backfill_macro()가 이미 존재하는 날짜는 update로 처리하는지 확인 (upsert 동작)."""
    # 먼저 하나의 기존 레코드 생성
    existing = MacroSnapshot(
        snapshot_date=date(2026, 3, 10),
        sp500_close=5700.0,
    )
    db.add(existing)
    await db.commit()

    mock_macro_list = [
        MacroData(
            snapshot_date=date(2026, 3, 10),
            sp500_close=5750.0,  # 업데이트될 값
            nasdaq_close=17900.0,
        ),
        MacroData(
            snapshot_date=date(2026, 3, 11),
            sp500_close=5760.0,
            nasdaq_close=17950.0,
        ),
    ]

    with patch(
        "app.services.macro_collector.fetch_macro_data_range",
        return_value=mock_macro_list,
    ):
        from app.services.macro_collector import backfill_macro

        result = await backfill_macro(
            db,
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 11),
        )

    # 기존 1건은 updated, 새 1건은 inserted
    assert result["updated"] == 1
    assert result["inserted"] == 1

    # 기존 레코드가 업데이트되었는지 확인
    row = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.snapshot_date == date(2026, 3, 10))
    )
    updated_snapshot = row.scalar_one()
    assert float(updated_snapshot.sp500_close) == pytest.approx(5750.0, abs=0.01)
    assert float(updated_snapshot.nasdaq_close) == pytest.approx(17900.0, abs=0.01)


async def test_backfill_macro_resume_from_last_state(db: AsyncSession):
    """중단 후 재시작 시 마지막 진행 시점의 상태가 저장되는지 확인."""
    mock_macro_list = [
        MacroData(
            snapshot_date=date(2026, 3, 15),
            sp500_close=5800.0,
        ),
        MacroData(
            snapshot_date=date(2026, 3, 16),
            sp500_close=5810.0,
        ),
    ]

    with patch(
        "app.services.macro_collector.fetch_macro_data_range",
        return_value=mock_macro_list,
    ):
        from app.services.macro_collector import backfill_macro, get_backfill_state

        await backfill_macro(
            db,
            start_date=date(2026, 3, 15),
            end_date=date(2026, 3, 16),
        )

        # 진행 상태가 저장되었는지 확인
        last_date = await get_backfill_state(db, "backfill_macro_last_date")

    assert last_date is not None
    # 마지막 처리된 날짜가 저장되어야 함
    assert last_date == "2026-03-16"


async def test_backfill_macro_dry_run(db: AsyncSession):
    """backfill_macro() dry_run 모드가 데이터를 적재하지 않는지 확인."""
    from app.services.macro_collector import backfill_macro

    result = await backfill_macro(
        db,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 5),
        dry_run=True,
    )

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["total_days"] == 5
    assert "to_fetch" in result

    # DB에 데이터가 없는지 확인
    rows = await db.execute(
        select(MacroSnapshot).where(
            MacroSnapshot.snapshot_date >= date(2026, 3, 1),
            MacroSnapshot.snapshot_date <= date(2026, 3, 5),
        )
    )
    assert len(rows.scalars().all()) == 0


# ── fetch_macro_data_range() 모킹 테스트 ──────────────────────────


async def test_fetch_macro_data_range_returns_list():
    """fetch_macro_data_range가 MacroData 리스트를 반환하는지 확인."""
    mock_range_data = {
        date(2026, 3, 1): {
            "sp500_close": 5800.0,
            "sp500_change_pct": 1.0,
        },
        date(2026, 3, 2): {
            "sp500_close": 5820.0,
            "sp500_change_pct": 0.34,
        },
    }

    with patch(
        "app.shared.macro_api._download_yfinance_range",
        return_value=mock_range_data,
    ):
        from app.shared.macro_api import fetch_macro_data_range

        results = await fetch_macro_data_range(date(2026, 3, 1), date(2026, 3, 2))

    assert len(results) == 2
    assert results[0].snapshot_date == date(2026, 3, 1)
    assert results[0].sp500_close == 5800.0
    assert results[1].snapshot_date == date(2026, 3, 2)
    assert results[1].sp500_close == 5820.0


# ── backfill_macro resume (이어서 수집) 통합 테스트 ─────────────────


async def test_backfill_macro_resume_continues_from_saved_state(db: AsyncSession):
    """첫 번째 백필 후, 두 번째 백필이 이어서 수집하는지 확인."""
    # 1차 백필: 3/20~3/21
    mock_first = [
        MacroData(snapshot_date=date(2026, 3, 20), sp500_close=5800.0),
        MacroData(snapshot_date=date(2026, 3, 21), sp500_close=5810.0),
    ]

    with patch(
        "app.services.macro_collector.fetch_macro_data_range",
        return_value=mock_first,
    ):
        from app.services.macro_collector import backfill_macro, get_backfill_state

        result1 = await backfill_macro(db, date(2026, 3, 20), date(2026, 3, 21))

    assert result1["inserted"] == 2

    # 진행 상태 확인
    last_date_str = await get_backfill_state(db, "backfill_macro_last_date")
    assert last_date_str == "2026-03-21"

    # 2차 백필: 3/22~3/23 (이어서 수집)
    mock_second = [
        MacroData(snapshot_date=date(2026, 3, 22), sp500_close=5820.0),
        MacroData(snapshot_date=date(2026, 3, 23), sp500_close=5830.0),
    ]

    with patch(
        "app.services.macro_collector.fetch_macro_data_range",
        return_value=mock_second,
    ):
        result2 = await backfill_macro(db, date(2026, 3, 22), date(2026, 3, 23))

    assert result2["inserted"] == 2

    # 전체 4일치 데이터 확인
    rows = await db.execute(
        select(MacroSnapshot)
        .where(
            MacroSnapshot.snapshot_date >= date(2026, 3, 20),
            MacroSnapshot.snapshot_date <= date(2026, 3, 23),
        )
        .order_by(MacroSnapshot.snapshot_date)
    )
    snapshots = rows.scalars().all()
    assert len(snapshots) == 4
