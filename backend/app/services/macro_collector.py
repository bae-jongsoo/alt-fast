"""매크로 데이터 수집 서비스."""

import asyncio
import logging
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.macro_snapshot import MacroSnapshot
from app.models.system_parameter import SystemParameter
from app.shared.macro_api import MacroData, fetch_macro_data, fetch_macro_data_range

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


async def _get_kr_base_rate(db: AsyncSession) -> float | None:
    """SystemParameter에서 한국 기준금리를 조회."""
    result = await db.execute(
        select(SystemParameter.value).where(
            SystemParameter.key == "kr_base_rate",
            SystemParameter.strategy_id.is_(None),
        )
    )
    value = result.scalar_one_or_none()
    if value is not None:
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning("kr_base_rate 파싱 실패: %s", value)
    return None


async def collect_macro_snapshot(db: AsyncSession, target_date: date | None = None) -> MacroSnapshot:
    """매크로 데이터를 수집하여 DB에 upsert."""
    if target_date is None:
        target_date = datetime.now(tz=KST).date()

    logger.info("매크로 스냅샷 수집 시작: %s", target_date)

    # yfinance 데이터 수집
    macro_data: MacroData = await fetch_macro_data(target_date)

    # 한국 기준금리 조회
    kr_base_rate = await _get_kr_base_rate(db)

    # 기존 레코드 확인 (upsert)
    result = await db.execute(
        select(MacroSnapshot).where(MacroSnapshot.snapshot_date == target_date)
    )
    snapshot = result.scalar_one_or_none()

    data_dict = macro_data.model_dump(exclude={"snapshot_date"})
    data_dict["kr_base_rate"] = kr_base_rate

    if snapshot:
        # 업데이트
        for key, value in data_dict.items():
            if value is not None:
                setattr(snapshot, key, value)
        logger.info("매크로 스냅샷 업데이트: %s", target_date)
    else:
        # 새 레코드 생성
        snapshot = MacroSnapshot(snapshot_date=target_date, **data_dict)
        db.add(snapshot)
        logger.info("매크로 스냅샷 생성: %s", target_date)

    await db.commit()
    await db.refresh(snapshot)

    # 수집 결과 요약 로그
    filled = sum(
        1 for k, v in data_dict.items() if v is not None and k != "raw_data"
    )
    total = len(data_dict) - 1  # raw_data 제외
    logger.info("매크로 스냅샷 수집 완료: %s (%d/%d 필드)", target_date, filled, total)

    return snapshot


async def backfill_macro(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    dry_run: bool = False,
) -> dict:
    """매크로 데이터를 기간별로 백필한다.

    Args:
        db: DB 세션
        start_date: 수집 시작일
        end_date: 수집 종료일 (inclusive)
        dry_run: True이면 수집 대상 건수만 반환

    Returns:
        {"total_days": int, "inserted": int, "updated": int, "skipped": int}
    """
    # 이미 존재하는 날짜 조회
    result = await db.execute(
        select(MacroSnapshot.snapshot_date).where(
            MacroSnapshot.snapshot_date >= start_date,
            MacroSnapshot.snapshot_date <= end_date,
        )
    )
    existing_dates = set(result.scalars().all())

    # 총 일수 계산 (주말 포함, yfinance가 거래일만 반환하므로)
    total_days = (end_date - start_date).days + 1

    if dry_run:
        return {
            "total_days": total_days,
            "existing": len(existing_dates),
            "to_fetch": total_days - len(existing_dates),
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
        }

    # 백필 시작 상태 저장
    await _save_backfill_state(db, "backfill_macro_last_date", start_date.isoformat())

    # yfinance에서 기간 데이터 일괄 수집
    logger.info("매크로 백필 시작: %s ~ %s", start_date, end_date)
    macro_list = await fetch_macro_data_range(start_date, end_date)

    kr_base_rate = await _get_kr_base_rate(db)

    inserted = 0
    updated = 0
    skipped = 0

    for macro_data in macro_list:
        d = macro_data.snapshot_date

        data_dict = macro_data.model_dump(exclude={"snapshot_date"})
        data_dict["kr_base_rate"] = kr_base_rate

        if d in existing_dates:
            # 기존 레코드 업데이트
            result = await db.execute(
                select(MacroSnapshot).where(MacroSnapshot.snapshot_date == d)
            )
            snapshot = result.scalar_one()
            for key, value in data_dict.items():
                if value is not None:
                    setattr(snapshot, key, value)
            updated += 1
        else:
            # 새 레코드 생성
            snapshot = MacroSnapshot(snapshot_date=d, **data_dict)
            db.add(snapshot)
            inserted += 1

        # 진행상황 로깅
        done = inserted + updated + skipped
        total = len(macro_list)
        if done % 10 == 0 or done == total:
            logger.info("매크로 백필 진행: %d/%d일 완료", done, total)

        # 진행 상태 저장
        await _save_backfill_state(db, "backfill_macro_last_date", d.isoformat())

    await db.commit()

    logger.info(
        "매크로 백필 완료: %s ~ %s (inserted=%d, updated=%d, skipped=%d)",
        start_date, end_date, inserted, updated, skipped,
    )

    return {
        "total_days": total_days,
        "existing": len(existing_dates),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }


async def _save_backfill_state(db: AsyncSession, key: str, value: str) -> None:
    """SystemParameter에 백필 진행 상태를 저장한다."""
    result = await db.execute(
        select(SystemParameter).where(
            SystemParameter.key == key,
            SystemParameter.strategy_id.is_(None),
        )
    )
    param = result.scalar_one_or_none()
    if param:
        param.value = value
    else:
        param = SystemParameter(key=key, value=value)
        db.add(param)
    await db.flush()


async def get_backfill_state(db: AsyncSession, key: str) -> str | None:
    """SystemParameter에서 백필 진행 상태를 조회한다."""
    result = await db.execute(
        select(SystemParameter.value).where(
            SystemParameter.key == key,
            SystemParameter.strategy_id.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def run_macro_collector() -> None:
    """매크로 수집 스케줄러: 08:30, 12:00에 수집."""
    from app.database import async_session

    schedule_times = [dt_time(8, 30), dt_time(12, 0)]

    logger.info("매크로 수집 스케줄러 시작 (08:30, 12:00)")

    while True:
        now = datetime.now(tz=KST)
        today = now.date()

        # 다음 실행 시각 계산
        next_run = None
        for t in schedule_times:
            candidate = datetime.combine(today, t, tzinfo=KST)
            if candidate > now:
                next_run = candidate
                break

        if next_run is None:
            # 오늘 모든 스케줄 지남 → 내일 첫 스케줄
            tomorrow = today + timedelta(days=1)
            next_run = datetime.combine(tomorrow, schedule_times[0], tzinfo=KST)

        wait_seconds = (next_run - now).total_seconds()
        logger.info("다음 매크로 수집: %s (%d초 대기)", next_run.isoformat(), int(wait_seconds))
        await asyncio.sleep(wait_seconds)

        # 수집 실행
        try:
            async with async_session() as db:
                snapshot = await collect_macro_snapshot(db)
                logger.info(
                    "매크로 수집 완료: id=%d, date=%s",
                    snapshot.id,
                    snapshot.snapshot_date,
                )
        except Exception:
            logger.exception("매크로 수집 오류")
