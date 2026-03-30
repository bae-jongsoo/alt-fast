"""매크로 수집기 테스트."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_snapshot import MacroSnapshot
from app.models.system_parameter import SystemParameter
from app.shared.macro_api import MacroData, TICKER_MAP


# ── MacroSnapshot 모델 CRUD 테스트 ──────────────────────────────


async def test_create_macro_snapshot(db: AsyncSession):
    """MacroSnapshot 생성 테스트."""
    snapshot = MacroSnapshot(
        snapshot_date=date(2026, 3, 28),
        sp500_close=5800.50,
        sp500_change_pct=1.23,
        nasdaq_close=18200.75,
        vix=15.5,
        usd_krw=1350.0,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    assert snapshot.id is not None
    assert snapshot.snapshot_date == date(2026, 3, 28)
    assert float(snapshot.sp500_close) == pytest.approx(5800.50, abs=0.01)
    assert float(snapshot.nasdaq_close) == pytest.approx(18200.75, abs=0.01)
    assert float(snapshot.vix) == pytest.approx(15.5, abs=0.01)
    assert float(snapshot.usd_krw) == pytest.approx(1350.0, abs=0.01)
    # nullable 필드는 None
    assert snapshot.dow_close is None
    assert snapshot.gold is None


async def test_query_macro_snapshot(db: AsyncSession):
    """MacroSnapshot 조회 테스트."""
    snapshot = MacroSnapshot(
        snapshot_date=date(2026, 3, 28),
        sp500_close=5800.50,
        nasdaq_close=18200.75,
    )
    db.add(snapshot)
    await db.commit()

    result = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.snapshot_date == date(2026, 3, 28))
    )
    found = result.scalar_one_or_none()
    assert found is not None
    assert float(found.sp500_close) == pytest.approx(5800.50, abs=0.01)


async def test_upsert_macro_snapshot(db: AsyncSession):
    """MacroSnapshot upsert(업데이트) 테스트."""
    snapshot = MacroSnapshot(
        snapshot_date=date(2026, 3, 25),
        sp500_close=5800.50,
    )
    db.add(snapshot)
    await db.commit()

    # 조회 후 업데이트
    result = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.snapshot_date == date(2026, 3, 25))
    )
    found = result.scalar_one()
    found.dow_close = 42000.0
    found.gold = 2100.5
    await db.commit()
    await db.refresh(found)

    assert float(found.dow_close) == pytest.approx(42000.0, abs=0.01)
    assert float(found.gold) == pytest.approx(2100.5, abs=0.01)
    # 기존 값 유지
    assert float(found.sp500_close) == pytest.approx(5800.50, abs=0.01)


# ── fetch_macro_data() 모킹 테스트 ──────────────────────────────


async def test_fetch_macro_data_success():
    """fetch_macro_data 정상 응답 모킹 테스트."""
    mock_raw = {
        "sp500_close": 5800.0,
        "sp500_change_pct": 1.5,
        "nasdaq_close": 18000.0,
        "nasdaq_change_pct": 2.0,
        "vix": 15.0,
        "vix_change_pct": -3.0,
        "usd_krw": 1350.0,
        "usd_krw_change_pct": 0.5,
    }

    with patch("app.shared.macro_api._download_yfinance", return_value=mock_raw):
        from app.shared.macro_api import fetch_macro_data

        data = await fetch_macro_data(date(2026, 3, 28))

    assert data.snapshot_date == date(2026, 3, 28)
    assert data.sp500_close == 5800.0
    assert data.nasdaq_close == 18000.0
    assert data.vix == 15.0
    assert data.usd_krw == 1350.0
    # 설정하지 않은 필드는 None
    assert data.dow_close is None
    assert data.gold is None


async def test_fetch_macro_data_partial_failure():
    """fetch_macro_data 부분 실패 시 나머지 필드는 정상."""
    # 일부 필드만 반환 (부분 실패 시나리오)
    mock_raw = {
        "sp500_close": 5800.0,
        "sp500_change_pct": 1.5,
        # nasdaq, dow 등은 실패로 없음
    }

    with patch("app.shared.macro_api._download_yfinance", return_value=mock_raw):
        from app.shared.macro_api import fetch_macro_data

        data = await fetch_macro_data(date(2026, 3, 28))

    assert data.sp500_close == 5800.0
    assert data.nasdaq_close is None
    assert data.dow_close is None
    assert data.vix is None


# ── collect_macro_snapshot() 서비스 테스트 ───────────────────────


async def test_collect_macro_snapshot_creates_new(db: AsyncSession):
    """collect_macro_snapshot 새 레코드 생성 테스트."""
    mock_data = MacroData(
        snapshot_date=date(2026, 3, 27),
        sp500_close=5750.0,
        sp500_change_pct=0.8,
        nasdaq_close=17900.0,
        vix=16.0,
        usd_krw=1345.0,
    )

    with patch("app.services.macro_collector.fetch_macro_data", return_value=mock_data):
        from app.services.macro_collector import collect_macro_snapshot

        snapshot = await collect_macro_snapshot(db, target_date=date(2026, 3, 27))

    assert snapshot.id is not None
    assert snapshot.snapshot_date == date(2026, 3, 27)
    assert float(snapshot.sp500_close) == pytest.approx(5750.0, abs=0.01)
    assert float(snapshot.vix) == pytest.approx(16.0, abs=0.01)


async def test_collect_macro_snapshot_upsert(db: AsyncSession):
    """collect_macro_snapshot 기존 레코드 업데이트 테스트."""
    # 먼저 레코드가 있는 상태에서 다시 수집
    mock_data = MacroData(
        snapshot_date=date(2026, 3, 27),
        sp500_close=5760.0,  # 값 변경
        sp500_change_pct=0.9,
        nasdaq_close=17950.0,
        vix=15.5,
        usd_krw=1348.0,
        gold=2150.0,  # 새 필드 추가
    )

    with patch("app.services.macro_collector.fetch_macro_data", return_value=mock_data):
        from app.services.macro_collector import collect_macro_snapshot

        snapshot = await collect_macro_snapshot(db, target_date=date(2026, 3, 27))

    assert float(snapshot.sp500_close) == pytest.approx(5760.0, abs=0.01)
    assert float(snapshot.gold) == pytest.approx(2150.0, abs=0.01)


async def test_collect_macro_snapshot_with_kr_base_rate(db: AsyncSession):
    """collect_macro_snapshot에서 kr_base_rate SystemParameter 반영 테스트."""
    # SystemParameter에 kr_base_rate 설정
    param = SystemParameter(key="kr_base_rate", value="2.75")
    db.add(param)
    await db.commit()

    mock_data = MacroData(
        snapshot_date=date(2026, 3, 26),
        sp500_close=5700.0,
    )

    with patch("app.services.macro_collector.fetch_macro_data", return_value=mock_data):
        from app.services.macro_collector import collect_macro_snapshot

        snapshot = await collect_macro_snapshot(db, target_date=date(2026, 3, 26))

    assert float(snapshot.kr_base_rate) == pytest.approx(2.75, abs=0.01)
