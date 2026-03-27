from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.report import DailyReportResponse
from app.services.report import generate_daily_report

KST = timezone(timedelta(hours=9))

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/daily", response_model=DailyReportResponse)
async def daily_report(
    target_date: date | None = Query(None, description="조회 날짜 (기본: 오늘)"),
    db: AsyncSession = Depends(get_db),
):
    if target_date is None:
        target_date = datetime.now(KST).date()
    return await generate_daily_report(db, target_date)
