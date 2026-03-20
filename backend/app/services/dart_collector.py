from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.target_stock import TargetStock
from app.shared.dart_api import fetch_disclosures

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _build_external_id(corp_code: str, rcept_no: str) -> str:
    raw = f"{corp_code}:{rcept_no}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


async def upsert_disclosures(
    session: AsyncSession,
    stock_code: str,
    corp_code: str,
    rows: list[dict],
) -> list[DartDisclosure]:
    """DART 공시 목록을 DB에 upsert 한다."""
    saved_disclosures: list[DartDisclosure] = []

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
            disclosure = DartDisclosure(external_id=external_id, **defaults)
            session.add(disclosure)
        else:
            for key, value in defaults.items():
                setattr(existing, key, value)
            disclosure = existing

        saved_disclosures.append(disclosure)

    if saved_disclosures:
        await session.commit()

    return saved_disclosures


async def collect_dart(
    session: AsyncSession,
    stock_codes: list[str] | None = None,
) -> dict:
    """DART 공시를 수집하여 DB에 저장한다."""
    target_corp_codes = await _resolve_target_corp_codes(session, stock_codes)

    fetched_items_count = 0
    saved_items_count = 0

    for stock_code, corp_code in target_corp_codes.items():
        try:
            rows = await fetch_disclosures(corp_code)
            fetched_items_count += len(rows)

            saved_rows = await upsert_disclosures(
                session, stock_code=stock_code, corp_code=corp_code, rows=rows,
            )
            saved_items_count += len(saved_rows)
            logger.info(
                "DART 공시 수집 완료: %s (corp=%s) - fetched=%d saved=%d",
                stock_code, corp_code, len(rows), len(saved_rows),
            )
        except Exception:
            logger.exception("DART 공시 수집 실패: %s (corp=%s)", stock_code, corp_code)

    return {
        "stock_codes": list(target_corp_codes.keys()),
        "fetched_items": fetched_items_count,
        "saved_items": saved_items_count,
    }


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
