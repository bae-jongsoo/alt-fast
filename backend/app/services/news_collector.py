from __future__ import annotations

import hashlib
import logging
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import News
from app.models.target_stock import TargetStock
from app.shared.llm import LLMAuthError, ask_llm_by_level, get_llm_level
from app.shared.naver_news import fetch_news
from app.shared.web_content import extract_article_text

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


NEWS_SUMMARY_PROMPT = """아래는 뉴스 본문이다. 이걸 요약하고 주식 단타에 도움이 되는지 판단 후,
{{"summary": "...", "useful": true}} 형태로 응답 해달라.

<뉴스 본문>
{article_text}
"""


async def _summarize_news(session: AsyncSession, news: News) -> None:
    """뉴스 본문을 크롤링하고 LLM으로 요약한다."""
    try:
        article_text = await extract_article_text(news.link)
    except Exception:
        news.summary = news.description
        news.useful = None
        await session.commit()
        return

    prompt = NEWS_SUMMARY_PROMPT.format(article_text=article_text)
    level = await get_llm_level("llm_news", "normal")
    raw_response = await ask_llm_by_level(level, prompt)

    import json
    # JSON 추출
    text = raw_response.strip()
    json_start = text.find("{")
    if json_start >= 0:
        text = text[json_start:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        news.summary = news.description
        news.useful = None
        await session.commit()
        return

    summary = (parsed.get("summary") or "").strip()
    useful = parsed.get("useful")

    if isinstance(useful, str):
        useful = useful.strip().lower() == "true"
    elif useful is not None:
        useful = bool(useful)

    news.summary = summary or news.description
    news.useful = useful
    await session.commit()


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

    # 요약이 없는 뉴스에 대해 LLM 요약 수행
    summarized = 0
    unsummarized = await session.execute(
        select(News).where(
            News.stock_code == stock_code,
            News.summary.is_(None),
        ).order_by(News.created_at.desc()).limit(limit)
    )
    for news in unsummarized.scalars().all():
        try:
            await _summarize_news(session, news)
            summarized += 1
        except LLMAuthError:
            logger.error("LLM 인증 실패, 요약 중단")
            break
        except Exception:
            logger.exception("뉴스 요약 실패 news_id=%s", news.id)

    return {"stock_code": stock_code, "fetched": len(items), "saved": saved, "skipped": skipped, "summarized": summarized}


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
