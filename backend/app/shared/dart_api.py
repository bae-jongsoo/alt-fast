from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import OpenDartReader

from app.config import settings

KST = timezone(timedelta(hours=9))


async def fetch_disclosures(corp_code: str, days: int = 7) -> list[dict]:
    """DART API에서 최근 공시 목록을 조회한다. (OpenDartReader는 동기이므로 executor에서 실행)"""
    api_key = settings.DART_API_KEY
    if not api_key:
        raise RuntimeError("DART_API_KEY 설정이 필요합니다")

    def _fetch() -> list[dict]:
        now = datetime.now(KST)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        reader = OpenDartReader(api_key)
        rows = reader.list(corp_code, start=start, end=end)

        if rows is None:
            return []
        if hasattr(rows, "to_dict"):
            return rows.to_dict("records")
        if isinstance(rows, dict):
            return [rows]
        return list(rows)

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise RuntimeError(f"OpenDartReader 호출 실패: {exc}") from exc
