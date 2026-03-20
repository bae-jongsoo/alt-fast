from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_snapshot import MarketSnapshot
from app.models.target_stock import TargetStock
from app.shared.kis import KisClient

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DECIMAL_FIELDS = [
    "per", "pbr", "eps", "bps", "cpfn",
    "w52_hgpr_vrss_prpr_ctrt", "w52_lwpr_vrss_prpr_ctrt",
    "d250_hgpr_vrss_prpr_rate", "d250_lwpr_vrss_prpr_rate",
    "dryy_hgpr_vrss_prpr_rate", "dryy_lwpr_vrss_prpr_rate",
    "hts_frgn_ehrt", "vol_tnrt", "whol_loan_rmnd_rate",
    "marg_rate", "apprch_rate",
]

INTEGER_FIELDS = [
    "hts_avls", "stck_fcam",
    "w52_hgpr", "w52_lwpr", "d250_hgpr", "d250_lwpr",
    "stck_dryy_hgpr", "stck_dryy_lwpr",
    "frgn_hldn_qty", "frgn_ntby_qty", "pgtr_ntby_qty",
    "last_ssts_cntg_qty",
]

DATE_FIELDS = [
    "w52_hgpr_date", "w52_lwpr_date",
    "d250_hgpr_date", "d250_lwpr_date",
    "dryy_hgpr_date", "dryy_lwpr_date",
]

STRING_FIELDS = [
    "stac_month", "lstn_stcn", "crdt_able_yn", "ssts_yn",
    "iscd_stat_cls_code", "mrkt_warn_cls_code", "invt_caful_yn",
    "short_over_yn", "sltr_yn", "mang_issu_cls_code", "temp_stop_yn",
    "oprc_rang_cont_yn", "clpr_rang_cont_yn", "grmn_rate_cls_code",
    "new_hgpr_lwpr_cls_code", "rprs_mrkt_kor_name", "bstp_kor_isnm",
    "vi_cls_code", "ovtm_vi_cls_code",
]

MARKET_COLLECT_FIELDS = [
    *DECIMAL_FIELDS[:4],
    "stac_month", "lstn_stcn", "hts_avls", "cpfn", "stck_fcam",
    "w52_hgpr", "w52_hgpr_date", "w52_hgpr_vrss_prpr_ctrt",
    "w52_lwpr", "w52_lwpr_date", "w52_lwpr_vrss_prpr_ctrt",
    "d250_hgpr", "d250_hgpr_date", "d250_hgpr_vrss_prpr_rate",
    "d250_lwpr", "d250_lwpr_date", "d250_lwpr_vrss_prpr_rate",
    "stck_dryy_hgpr", "dryy_hgpr_date", "dryy_hgpr_vrss_prpr_rate",
    "stck_dryy_lwpr", "dryy_lwpr_date", "dryy_lwpr_vrss_prpr_rate",
    "hts_frgn_ehrt", "frgn_hldn_qty", "frgn_ntby_qty", "pgtr_ntby_qty",
    "vol_tnrt", "whol_loan_rmnd_rate", "marg_rate",
    "crdt_able_yn", "ssts_yn", "iscd_stat_cls_code", "mrkt_warn_cls_code",
    "invt_caful_yn", "short_over_yn", "sltr_yn", "mang_issu_cls_code",
    "temp_stop_yn", "oprc_rang_cont_yn", "clpr_rang_cont_yn",
    "grmn_rate_cls_code", "new_hgpr_lwpr_cls_code",
    "rprs_mrkt_kor_name", "bstp_kor_isnm",
    "vi_cls_code", "ovtm_vi_cls_code",
    "last_ssts_cntg_qty", "apprch_rate",
]


def _build_external_id(stock_code: str, published_at: datetime) -> str:
    raw = f"{stock_code}:{published_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def normalize_market_snapshot(stock_code: str, payload: dict) -> dict:
    published_at = _parse_published_at(payload.get("published_at"))

    normalized: dict = {
        "stock_code": stock_code,
        "published_at": published_at,
    }

    for field in DECIMAL_FIELDS:
        normalized[field] = _parse_decimal(payload.get(field), field)
    for field in INTEGER_FIELDS:
        normalized[field] = _parse_integer(payload.get(field), field)
    for field in DATE_FIELDS:
        normalized[field] = _parse_date(payload.get(field), field)
    for field in STRING_FIELDS:
        normalized[field] = _parse_string(payload.get(field))

    return normalized


async def upsert_market_snapshot(session: AsyncSession, snapshot_data: dict) -> MarketSnapshot:
    published_at = snapshot_data.get("published_at")
    if published_at in (None, ""):
        raise ValueError("external_id 생성에 필요한 시각값이 없습니다: published_at 필수")

    external_id = _build_external_id(snapshot_data["stock_code"], published_at)

    result = await session.execute(
        select(MarketSnapshot).where(MarketSnapshot.external_id == external_id)
    )
    snapshot = result.scalar_one_or_none()

    defaults = {"stock_code": snapshot_data["stock_code"], "published_at": published_at}
    for field in MARKET_COLLECT_FIELDS:
        defaults[field] = snapshot_data.get(field)

    if snapshot is None:
        snapshot = MarketSnapshot(external_id=external_id, **defaults)
        session.add(snapshot)
    else:
        for key, value in defaults.items():
            setattr(snapshot, key, value)

    await session.commit()
    return snapshot


async def collect_market_snapshots(
    session: AsyncSession,
    stock_codes: list[str] | None = None,
) -> dict:
    """시장 스냅샷을 수집하여 DB에 저장한다."""
    target_stock_codes = await _resolve_stock_codes(session, stock_codes)

    fetched_items_count = 0
    saved_items_count = 0

    client = KisClient()
    for stock_code in target_stock_codes:
        try:
            payload = await client.fetch_inquire_price(stock_code)
            now_kst = datetime.now(KST).replace(tzinfo=None)
            payload.setdefault("published_at", now_kst.isoformat())
            fetched_items_count += 1

            snapshot_data = normalize_market_snapshot(stock_code, payload)
            await upsert_market_snapshot(session, snapshot_data)
            saved_items_count += 1
            logger.info("시장 스냅샷 저장 완료: %s", stock_code)
        except Exception:
            logger.exception("시장 스냅샷 수집 실패: %s", stock_code)

    return {
        "stock_codes": target_stock_codes,
        "fetched_items": fetched_items_count,
        "saved_items": saved_items_count,
    }


async def _resolve_stock_codes(session: AsyncSession, stock_codes: list[str] | None) -> list[str]:
    if stock_codes:
        return stock_codes
    result = await session.execute(
        select(TargetStock.stock_code).where(TargetStock.is_active.is_(True))
    )
    return list(result.scalars().all())


# -- 파싱 유틸리티 ------------------------------------------------

def _parse_published_at(raw_value: object) -> datetime:
    if raw_value in (None, ""):
        raise ValueError("external_id 생성에 필요한 시각값이 없습니다: published_at 필수")

    raw_text = str(raw_value).strip()

    # ISO format
    try:
        parsed = datetime.fromisoformat(raw_text)
        if parsed.tzinfo is not None:
            return parsed.astimezone(KST).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass

    # compact datetime: 20250101120000
    parsed = _parse_compact_datetime(raw_text)
    if parsed is not None:
        return parsed

    # date only
    parsed_date = _parse_flexible_date(raw_text)
    if parsed_date is not None:
        return datetime.combine(parsed_date, datetime.min.time())

    raise ValueError("숫자/날짜 파싱 변환 실패: published_at")


def _parse_decimal(raw_value: object, field_name: str) -> Decimal | None:
    if raw_value in (None, ""):
        return None
    try:
        return Decimal(str(raw_value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"숫자/날짜 파싱 변환 실패: {field_name}") from exc


def _parse_integer(raw_value: object, field_name: str) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        numeric = Decimal(str(raw_value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"숫자/날짜 파싱 변환 실패: {field_name}") from exc
    if numeric != numeric.to_integral_value():
        raise ValueError(f"숫자/날짜 파싱 변환 실패: {field_name}")
    return int(numeric)


def _parse_date(raw_value: object, field_name: str) -> date | None:
    if raw_value in (None, ""):
        return None
    raw_text = str(raw_value).strip()
    parsed = _parse_flexible_date(raw_text)
    if parsed is not None:
        return parsed
    raise ValueError(f"숫자/날짜 파싱 변환 실패: {field_name}")


def _parse_string(raw_value: object) -> str:
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _parse_flexible_date(raw_text: str) -> date | None:
    # YYYY-MM-DD
    try:
        return date.fromisoformat(raw_text)
    except ValueError:
        pass
    # YYYYMMDD
    if len(raw_text) == 8 and raw_text.isdigit():
        try:
            return date.fromisoformat(f"{raw_text[:4]}-{raw_text[4:6]}-{raw_text[6:8]}")
        except ValueError:
            pass
    return None


def _parse_compact_datetime(raw_text: str) -> datetime | None:
    if len(raw_text) == 14 and raw_text.isdigit():
        try:
            return datetime.fromisoformat(
                f"{raw_text[:4]}-{raw_text[4:6]}-{raw_text[6:8]}T"
                f"{raw_text[8:10]}:{raw_text[10:12]}:{raw_text[12:14]}"
            )
        except ValueError:
            return None
    return None
