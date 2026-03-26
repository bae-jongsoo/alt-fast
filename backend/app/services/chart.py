from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.minute_candle import MinuteCandle
from app.schemas.chart import CandleItem, CandleListResponse


async def get_candles(
    db: AsyncSession,
    stock_code: str,
    start: date,
    end: date,
) -> CandleListResponse:
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    result = await db.execute(
        select(MinuteCandle)
        .where(
            MinuteCandle.stock_code == stock_code,
            MinuteCandle.minute_at >= start_dt,
            MinuteCandle.minute_at <= end_dt,
        )
        .order_by(MinuteCandle.minute_at.asc())
    )
    candles = result.scalars().all()

    return CandleListResponse(
        items=[
            CandleItem(
                minute_at=c.minute_at,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles
        ]
    )
