from __future__ import annotations

import hashlib
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import News
from app.models.target_stock import TargetStock
from app.shared.naver_news import fetch_news

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _build_external_id(stock_code: str, link: str) -> str:
    raw = f"{stock_code}:{link}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _parse_published_at(raw_pub_date: str | None) -> datetime:
    if raw_pub_date:
        try:
            dt = parsedate_to_datetime(raw_pub_date)
            return dt.astimezone(KST).replace(tzinfo=None)
        except (TypeError, ValueError, IndexError):
            pass
    return datetime.now(KST).replace(tzinfo=None)


async def collect_news_for_stock(
    session: AsyncSession,
    stock_code: str,
    stock_name: str,
    limit: int = 10,
) -> dict:
    """한 종목의 뉴스를 수집하여 DB에 저장한다."""
    items = await fetch_news(stock_name, limit)

    saved = 0
    skipped = 0
    for item in items:
        link = (item.get("link") or "").strip()
        if not link:
            continue

        external_id = _build_external_id(stock_code, link)

        # 이미 존재하면 스킵
        existing = await session.execute(
            select(News.id).where(News.external_id == external_id)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        news = News(
            stock_code=stock_code,
            stock_name=stock_name,
            title=(item.get("title") or "").strip(),
            description=(item.get("description") or "").strip() or None,
            link=link,
            external_id=external_id,
            published_at=_parse_published_at(item.get("pubDate")),
            summary=None,
            useful=None,
        )
        session.add(news)
        saved += 1

    if saved > 0:
        await session.commit()

    return {"stock_code": stock_code, "fetched": len(items), "saved": saved, "skipped": skipped}


async def collect_all_news(
    session: AsyncSession,
    stock_codes: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """모든 대상 종목의 뉴스를 수집한다."""
    if stock_codes:
        result = await session.execute(
            select(TargetStock).where(
                TargetStock.stock_code.in_(stock_codes),
                TargetStock.is_active.is_(True),
            )
        )
    else:
        result = await session.execute(
            select(TargetStock).where(TargetStock.is_active.is_(True))
        )
    stocks = result.scalars().all()

    results = []
    for stock in stocks:
        try:
            r = await collect_news_for_stock(session, stock.stock_code, stock.stock_name, limit)
            results.append(r)
            logger.info("뉴스 수집 완료: %s (%s) - fetched=%d saved=%d skipped=%d",
                        stock.stock_name, stock.stock_code, r["fetched"], r["saved"], r["skipped"])
        except Exception:
            logger.exception("뉴스 수집 실패: %s (%s)", stock.stock_name, stock.stock_code)
            results.append({"stock_code": stock.stock_code, "error": True})

    return results
