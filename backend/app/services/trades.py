from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.schemas.trades import (
    DecisionDetailResponse,
    DecisionHistoryItem,
    DecisionHistoryListResponse,
    OrderHistoryItem,
    OrderHistoryListResponse,
    SourceItem,
)


def _to_order_item(o: OrderHistory) -> OrderHistoryItem:
    return OrderHistoryItem(
        id=o.id,
        created_at=o.created_at,
        stock_code=o.stock_code,
        stock_name=o.stock_name or "",
        order_type=o.order_type,
        order_price=float(o.order_price),
        quantity=o.order_quantity,
        total_amount=float(o.order_total_amount),
        profit_loss=float(o.profit_loss) if o.profit_loss is not None else None,
        profit_rate=float(o.profit_rate) if o.profit_rate is not None else None,
        profit_rate_net=float(o.profit_rate_net) if o.profit_rate_net is not None else None,
        decision_history_id=o.decision_history_id,
    )


async def get_orders(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    order_type: str | None = None,
    stock_code: str | None = None,
) -> OrderHistoryListResponse:
    if start_date is None:
        start_date = (datetime.now(KST).replace(tzinfo=None) - timedelta(days=7)).date()
    if end_date is None:
        end_date = datetime.now(KST).replace(tzinfo=None).date()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    base = select(OrderHistory).where(
        OrderHistory.created_at >= start_dt,
        OrderHistory.created_at <= end_dt,
    )
    count_base = select(func.count()).select_from(OrderHistory).where(
        OrderHistory.created_at >= start_dt,
        OrderHistory.created_at <= end_dt,
    )

    if order_type:
        base = base.where(OrderHistory.order_type == order_type)
        count_base = count_base.where(OrderHistory.order_type == order_type)
    if stock_code:
        base = base.where(OrderHistory.stock_code == stock_code)
        count_base = count_base.where(OrderHistory.stock_code == stock_code)

    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(OrderHistory.created_at.desc()).offset(offset).limit(page_size)
    )
    orders = result.scalars().all()

    return OrderHistoryListResponse(
        items=[_to_order_item(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_decisions(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    decision: str | None = None,
    stock_code: str | None = None,
    errors_only: bool = False,
) -> DecisionHistoryListResponse:
    if start_date is None:
        start_date = (datetime.now(KST).replace(tzinfo=None) - timedelta(days=7)).date()
    if end_date is None:
        end_date = datetime.now(KST).replace(tzinfo=None).date()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    base = select(DecisionHistory).where(
        DecisionHistory.created_at >= start_dt,
        DecisionHistory.created_at <= end_dt,
    )
    count_base = select(func.count()).select_from(DecisionHistory).where(
        DecisionHistory.created_at >= start_dt,
        DecisionHistory.created_at <= end_dt,
    )

    if decision:
        base = base.where(DecisionHistory.decision == decision)
        count_base = count_base.where(DecisionHistory.decision == decision)
    if stock_code:
        base = base.where(DecisionHistory.stock_code == stock_code)
        count_base = count_base.where(DecisionHistory.stock_code == stock_code)
    if errors_only:
        base = base.where(DecisionHistory.is_error.is_(True))
        count_base = count_base.where(DecisionHistory.is_error.is_(True))

    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(DecisionHistory.created_at.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    def _extract_sources(d: DecisionHistory) -> list[SourceItem] | None:
        pd = d.parsed_decision
        if not pd or not isinstance(pd, dict):
            return None
        raw = pd.get("decision", {}).get("sources")
        if not raw or not isinstance(raw, list):
            return None
        return [
            SourceItem(
                type=s.get("type", ""),
                weight=s.get("weight", 0),
                detail=s.get("detail", ""),
            )
            for s in raw
            if isinstance(s, dict)
        ]

    return DecisionHistoryListResponse(
        items=[
            DecisionHistoryItem(
                id=d.id,
                created_at=d.created_at,
                stock_code=d.stock_code,
                stock_name=d.stock_name or "",
                decision=d.decision,
                is_error=d.is_error,
                error_message=d.error_message,
                sources=_extract_sources(d),
            )
            for d in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_decision_detail(
    db: AsyncSession,
    decision_id: int,
) -> DecisionDetailResponse | None:
    result = await db.execute(
        select(DecisionHistory).where(DecisionHistory.id == decision_id)
    )
    d = result.scalar_one_or_none()
    if not d:
        return None

    # 연결된 주문 조회
    order_result = await db.execute(
        select(OrderHistory).where(OrderHistory.decision_history_id == d.id).limit(1)
    )
    linked = order_result.scalar_one_or_none()

    return DecisionDetailResponse(
        id=d.id,
        created_at=d.created_at,
        stock_code=d.stock_code,
        stock_name=d.stock_name or "",
        decision=d.decision,
        request_payload=d.request_payload,
        response_payload=d.response_payload,
        parsed_decision=d.parsed_decision,
        is_error=d.is_error,
        error_message=d.error_message,
        linked_order=_to_order_item(linked) if linked else None,
    )
