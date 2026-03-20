from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.news import News
from app.schemas.news import (
    DartItem,
    DartListResponse,
    NewsItem,
    NewsListResponse,
)


async def get_news(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    stock_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    useful: str | None = None,
) -> NewsListResponse:
    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=7)).date()
    if end_date is None:
        end_date = datetime.utcnow().date()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    base = select(News).where(News.created_at >= start_dt, News.created_at <= end_dt)
    count_q = select(func.count()).select_from(News).where(News.created_at >= start_dt, News.created_at <= end_dt)

    if stock_code:
        base = base.where(News.stock_code == stock_code)
        count_q = count_q.where(News.stock_code == stock_code)

    if useful is not None and useful != "all":
        if useful == "null":
            base = base.where(News.useful.is_(None))
            count_q = count_q.where(News.useful.is_(None))
        elif useful == "true":
            base = base.where(News.useful.is_(True))
            count_q = count_q.where(News.useful.is_(True))
        elif useful == "false":
            base = base.where(News.useful.is_(False))
            count_q = count_q.where(News.useful.is_(False))

    total = (await db.execute(count_q)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(News.published_at.desc().nulls_last()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return NewsListResponse(
        items=[
            NewsItem(
                id=n.id, stock_code=n.stock_code, stock_name=n.stock_name or "",
                title=n.title, summary=n.summary, url=n.link,
                useful=n.useful, published_at=n.published_at,
            )
            for n in items
        ],
        total=total, page=page, page_size=page_size,
    )


async def get_dart(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    stock_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DartListResponse:
    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=7)).date()
    if end_date is None:
        end_date = datetime.utcnow().date()

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    base = select(DartDisclosure).where(
        DartDisclosure.created_at >= start_dt, DartDisclosure.created_at <= end_dt,
    )
    count_q = select(func.count()).select_from(DartDisclosure).where(
        DartDisclosure.created_at >= start_dt, DartDisclosure.created_at <= end_dt,
    )

    if stock_code:
        base = base.where(DartDisclosure.stock_code == stock_code)
        count_q = count_q.where(DartDisclosure.stock_code == stock_code)

    total = (await db.execute(count_q)).scalar() or 0
    offset = (page - 1) * page_size
    result = await db.execute(
        base.order_by(DartDisclosure.published_at.desc().nulls_last()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return DartListResponse(
        items=[
            DartItem(
                id=d.id, stock_code=d.stock_code, stock_name=d.stock_name or "",
                title=d.title, description=d.description, rcept_no=d.rcept_no,
                url=d.link, published_at=d.published_at,
            )
            for d in items
        ],
        total=total, page=page, page_size=page_size,
    )
