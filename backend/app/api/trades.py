from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.trades import (
    DecisionDetailResponse,
    DecisionHistoryListResponse,
    OrderHistoryListResponse,
)
from app.services.trades import get_decision_detail, get_decisions, get_orders

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/orders", response_model=OrderHistoryListResponse)
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    order_type: str | None = None,
    stock_code: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_orders(db, page, page_size, start_date, end_date, order_type, stock_code)


@router.get("/decisions", response_model=DecisionHistoryListResponse)
async def list_decisions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    decision: str | None = None,
    stock_code: str | None = None,
    errors_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    return await get_decisions(db, page, page_size, start_date, end_date, decision, stock_code, errors_only)


@router.get("/decisions/{decision_id}", response_model=DecisionDetailResponse)
async def decision_detail(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await get_decision_detail(db, decision_id)
    if not result:
        raise HTTPException(status_code=404, detail="판단 이력을 찾을 수 없습니다")
    return result
