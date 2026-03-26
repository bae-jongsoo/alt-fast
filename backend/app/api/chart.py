from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chart import CandleListResponse
from app.services.chart import get_candles

KST = timezone(timedelta(hours=9))

router = APIRouter(prefix="/api/chart", tags=["chart"])


@router.get("/candles", response_model=CandleListResponse)
async def list_candles(
    stock_code: str = Query(..., min_length=1, max_length=6),
    start: date | None = None,
    end: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(KST).date()
    if start is None:
        start = today
    if end is None:
        end = today
    return await get_candles(db, stock_code, start, end)
