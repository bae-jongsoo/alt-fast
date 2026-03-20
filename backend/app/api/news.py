from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.news import DartListResponse, NewsListResponse
from app.services.news import get_dart, get_news

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news", response_model=NewsListResponse)
async def list_news(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    stock_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    useful: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_news(db, page, page_size, stock_code, start_date, end_date, useful)


@router.get("/dart", response_model=DartListResponse)
async def list_dart(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    stock_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_dart(db, page, page_size, stock_code, start_date, end_date)
