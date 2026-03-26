from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.minute_candle import MinuteCandle
from app.models.target_stock import TargetStock
from app.shared.kis import KisClient

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


async def backfill_candles(
    session: AsyncSession,
    stock_codes: list[str] | None = None,
    target_date: datetime | None = None,
) -> dict:
    """KIS 당일분봉조회 API를 이용해 빈 분봉 데이터를 보충한다.

    Args:
        session: DB 세션
        stock_codes: 대상 종목코드 리스트 (None이면 활성 종목 전체)
        target_date: 대상 날짜 (None이면 오늘, KST 기준)

    Returns:
        보충 결과 요약 dict
    """
    if target_date is None:
        target_date = datetime.now(KST)

    target_date_naive = datetime(
        target_date.year, target_date.month, target_date.day
    )

    if stock_codes is None:
        result = await session.execute(
            select(TargetStock.stock_code).where(TargetStock.is_active.is_(True))
        )
        stock_codes = list(result.scalars().all())

    if not stock_codes:
        logger.warning("보충 대상 종목이 없습니다")
        return {"stock_codes": [], "fetched": 0, "inserted": 0, "skipped": 0}

    client = KisClient()
    total_fetched = 0
    total_inserted = 0
    total_skipped = 0

    for stock_code in stock_codes:
        try:
            fetched, inserted, skipped = await _backfill_stock(
                session, client, stock_code, target_date_naive
            )
            total_fetched += fetched
            total_inserted += inserted
            total_skipped += skipped
            logger.info(
                "분봉 보충 완료: %s fetched=%d inserted=%d skipped=%d",
                stock_code, fetched, inserted, skipped,
            )
        except Exception:
            logger.exception("분봉 보충 실패: %s", stock_code)

        # KIS API rate limit (초당 10건)
        await asyncio.sleep(0.15)

    return {
        "stock_codes": stock_codes,
        "fetched": total_fetched,
        "inserted": total_inserted,
        "skipped": total_skipped,
    }


async def _backfill_stock(
    session: AsyncSession,
    client: KisClient,
    stock_code: str,
    target_date_naive: datetime,
) -> tuple[int, int, int]:
    """단일 종목의 분봉 보충. (fetched, inserted, skipped) 반환."""
    raw_candles = await client.fetch_minute_candles(stock_code)
    fetched = len(raw_candles)
    inserted = 0
    skipped = 0

    for raw in raw_candles:
        candle_time = raw.get("stck_cntg_hour", "")
        if len(candle_time) < 6:
            continue

        hour = int(candle_time[0:2])
        minute = int(candle_time[2:4])
        minute_at = target_date_naive.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # DB에 이미 존재하는지 확인
        result = await session.execute(
            select(MinuteCandle.id).where(
                MinuteCandle.stock_code == stock_code,
                MinuteCandle.minute_at == minute_at,
            )
        )
        if result.scalar_one_or_none() is not None:
            skipped += 1
            continue

        try:
            open_price = int(raw.get("stck_oprc", 0))
            high_price = int(raw.get("stck_hgpr", 0))
            low_price = int(raw.get("stck_lwpr", 0))
            close_price = int(raw.get("stck_prpr", 0))
            volume = int(raw.get("cntg_vol", 0))
        except (ValueError, TypeError):
            logger.warning("분봉 데이터 파싱 실패: %s %s", stock_code, candle_time)
            continue

        if close_price == 0:
            continue

        candle = MinuteCandle(
            stock_code=stock_code,
            minute_at=minute_at,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
        )
        session.add(candle)
        inserted += 1

    if inserted > 0:
        await session.commit()

    return fetched, inserted, skipped
