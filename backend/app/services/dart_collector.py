from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.dart_disclosure import DartDisclosure
from app.models.target_stock import TargetStock
from app.shared.dart_api import fetch_disclosures

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

REDIS_KEY_DART_NEW = "event:dart:new"


def _build_external_id(corp_code: str, rcept_no: str) -> str:
    raw = f"{corp_code}:{rcept_no}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


async def _notify_new_disclosures(
    new_ids: list[int],
    redis_client: aioredis.Redis | None = None,
) -> None:
    """신규 공시 ID를 Redis List에 RPUSH하여 event_trader가 감지할 수 있도록 한다."""
    if not new_ids:
        return

    should_close = False
    if redis_client is None:
        try:
            redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            should_close = True
        except Exception:
            logger.warning("Redis 연결 실패, 신규 공시 알림 스킵")
            return

    try:
        await redis_client.rpush(REDIS_KEY_DART_NEW, *[str(id_) for id_ in new_ids])
        logger.info("Redis 알림 전송: %d건 신규 공시 → %s", len(new_ids), REDIS_KEY_DART_NEW)
    except Exception:
        logger.warning("Redis 알림 전송 실패", exc_info=True)
    finally:
        if should_close and redis_client is not None:
            await redis_client.aclose()


async def upsert_disclosures(
    session: AsyncSession,
    stock_code: str,
    corp_code: str,
    rows: list[dict],
) -> tuple[list[DartDisclosure], list[int]]:
    """DART 공시 목록을 DB에 upsert 한다.

    Returns:
        (saved_disclosures, new_ids) - 저장된 공시 목록과 신규 INSERT된 공시 ID 목록
    """
    saved_disclosures: list[DartDisclosure] = []
    new_disclosures: list[DartDisclosure] = []

    for row in rows:
        rcept_no = (row.get("rcept_no") or "").strip()
        if not rcept_no:
            raise ValueError("rcept_no가 없어 external_id 생성 불가: rcept_no/external_id 필수")

        external_id = _build_external_id(corp_code, rcept_no)

        result = await session.execute(
            select(DartDisclosure).where(DartDisclosure.external_id == external_id)
        )
        existing = result.scalar_one_or_none()

        defaults = {
            "stock_code": stock_code,
            "corp_code": corp_code,
            "rcept_no": rcept_no,
            "title": (row.get("title") or row.get("report_nm") or "").strip(),
            "link": (row.get("link") or "").strip(),
            "description": _normalize_description(row.get("description")),
            "published_at": _normalize_published_at(row.get("published_at") or row.get("rcept_dt")),
        }

        if existing is None:
            disclosure = DartDisclosure(external_id=external_id, is_processed=False, **defaults)
            session.add(disclosure)
            new_disclosures.append(disclosure)
        else:
            for key, value in defaults.items():
                setattr(existing, key, value)
            disclosure = existing

        saved_disclosures.append(disclosure)

    if saved_disclosures:
        await session.commit()

    # commit 후 ID가 할당되므로 여기서 추출
    new_ids = [d.id for d in new_disclosures]

    return saved_disclosures, new_ids


async def backfill_dart(
    session: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    stock_codes: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """DART 공시를 기간별로 백필한다.

    DART API의 날짜 범위 조회를 활용하며, 주 단위로 나누어 수집한다.

    Args:
        session: DB 세션
        start_date: 수집 시작일
        end_date: 수집 종료일
        stock_codes: 대상 종목코드 (None이면 활성 종목 전체)
        dry_run: True이면 수집 대상 건수만 반환

    Returns:
        수집 결과 요약 dict
    """
    target_corp_codes = await _resolve_target_corp_codes(session, stock_codes)

    if not target_corp_codes:
        return {"stock_codes": [], "fetched": 0, "saved": 0, "new": 0}

    total_days = (end_date - start_date).days + 1

    if dry_run:
        return {
            "stock_codes": list(target_corp_codes.keys()),
            "total_days": total_days,
            "fetched": 0,
            "saved": 0,
            "new": 0,
        }

    total_fetched = 0
    total_saved = 0
    total_new = 0

    # 주 단위로 나누어 수집 (DART API 제한 고려)
    current = start_date
    week_delta = timedelta(days=7)

    while current <= end_date:
        week_end = min(current + week_delta - timedelta(days=1), end_date)
        days_in_range = (week_end - current).days + 1

        for stock_code, corp_code in target_corp_codes.items():
            try:
                rows = await fetch_disclosures(corp_code, days=days_in_range)
                total_fetched += len(rows)

                saved_rows, new_ids = await upsert_disclosures(
                    session, stock_code=stock_code, corp_code=corp_code, rows=rows,
                )
                total_saved += len(saved_rows)
                total_new += len(new_ids)

                logger.info(
                    "DART 백필: %s (%s~%s) fetched=%d saved=%d new=%d",
                    stock_code, current.strftime("%Y-%m-%d"),
                    week_end.strftime("%Y-%m-%d"),
                    len(rows), len(saved_rows), len(new_ids),
                )
            except Exception:
                logger.exception(
                    "DART 백필 실패: %s (%s~%s)",
                    stock_code, current.strftime("%Y-%m-%d"),
                    week_end.strftime("%Y-%m-%d"),
                )

            # Rate limiting
            await asyncio.sleep(0.5)

        current = week_end + timedelta(days=1)

    return {
        "stock_codes": list(target_corp_codes.keys()),
        "total_days": total_days,
        "fetched": total_fetched,
        "saved": total_saved,
        "new": total_new,
    }


async def collect_dart(
    session: AsyncSession,
    stock_codes: list[str] | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict:
    """DART 공시를 수집하여 DB에 저장한다."""
    target_corp_codes = await _resolve_target_corp_codes(session, stock_codes)

    fetched_items_count = 0
    saved_items_count = 0
    new_items_count = 0
    all_new_ids: list[int] = []

    for stock_code, corp_code in target_corp_codes.items():
        try:
            rows = await fetch_disclosures(corp_code)
            fetched_items_count += len(rows)

            saved_rows, new_ids = await upsert_disclosures(
                session, stock_code=stock_code, corp_code=corp_code, rows=rows,
            )
            saved_items_count += len(saved_rows)
            new_items_count += len(new_ids)
            all_new_ids.extend(new_ids)
            logger.info(
                "DART 공시 수집 완료: %s (corp=%s) - fetched=%d saved=%d new=%d",
                stock_code, corp_code, len(rows), len(saved_rows), len(new_ids),
            )
        except Exception:
            logger.exception("DART 공시 수집 실패: %s (corp=%s)", stock_code, corp_code)

    # 신규 공시가 있으면 Redis로 알림
    if all_new_ids:
        await _notify_new_disclosures(all_new_ids, redis_client=redis_client)
        logger.info("신규 공시 총 %d건 감지", new_items_count)

    return {
        "stock_codes": list(target_corp_codes.keys()),
        "fetched_items": fetched_items_count,
        "saved_items": saved_items_count,
        "new_items": new_items_count,
    }


async def get_unprocessed_disclosures(
    db: AsyncSession,
    stock_codes: list[str] | None = None,
    limit: int = 10,
) -> list[DartDisclosure]:
    """미처리 공시를 조회한다.

    Args:
        db: DB 세션
        stock_codes: 특정 종목코드 필터 (None이면 전체)
        limit: 최대 조회 건수

    Returns:
        is_processed=False인 공시 목록 (published_at 내림차순)
    """
    stmt = select(DartDisclosure).where(DartDisclosure.is_processed.is_(False))
    if stock_codes:
        stmt = stmt.where(DartDisclosure.stock_code.in_(stock_codes))
    stmt = stmt.order_by(DartDisclosure.published_at.desc()).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_disclosure_processed(
    db: AsyncSession,
    disclosure_id: int,
) -> None:
    """공시를 처리 완료로 표시한다."""
    result = await db.execute(
        select(DartDisclosure).where(DartDisclosure.id == disclosure_id)
    )
    disclosure = result.scalar_one_or_none()
    if disclosure is not None:
        disclosure.is_processed = True
        await db.commit()


async def _resolve_target_corp_codes(
    session: AsyncSession,
    stock_codes: list[str] | None,
) -> dict[str, str]:
    """TargetStock 테이블에서 stock_code -> dart_corp_code 매핑을 조회."""
    if stock_codes:
        result = await session.execute(
            select(TargetStock).where(
                TargetStock.stock_code.in_(stock_codes),
                TargetStock.is_active.is_(True),
                TargetStock.dart_corp_code.isnot(None),
            )
        )
    else:
        result = await session.execute(
            select(TargetStock).where(
                TargetStock.is_active.is_(True),
                TargetStock.dart_corp_code.isnot(None),
            )
        )

    stocks = result.scalars().all()
    mapping = {}
    for stock in stocks:
        if stock.dart_corp_code:
            mapping[stock.stock_code] = stock.dart_corp_code

    if not mapping:
        logger.warning("DART corp_code가 설정된 활성 종목이 없습니다")

    return mapping


def _normalize_description(raw_description: object) -> str | None:
    if raw_description is None:
        return None
    return str(raw_description).strip() or None


def _normalize_published_at(raw_published_at: object) -> datetime | None:
    if raw_published_at in (None, ""):
        return None
    if isinstance(raw_published_at, datetime):
        if raw_published_at.tzinfo is not None:
            return raw_published_at.astimezone(KST).replace(tzinfo=None)
        return raw_published_at
    if isinstance(raw_published_at, str):
        raw_text = raw_published_at.strip()
        # ISO format
        try:
            dt = datetime.fromisoformat(raw_text)
            if dt.tzinfo is not None:
                return dt.astimezone(KST).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
        # YYYYMMDD
        if len(raw_text) == 8 and raw_text.isdigit():
            try:
                return datetime.fromisoformat(
                    f"{raw_text[:4]}-{raw_text[4:6]}-{raw_text[6:8]}T00:00:00"
                )
            except ValueError:
                pass
    return None
