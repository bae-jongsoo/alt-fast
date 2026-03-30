from __future__ import annotations

import asyncio
import hashlib
import logging
from email.utils import parsedate_to_datetime
from datetime import date, datetime, timedelta, timezone

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


async def backfill_news(
    session: AsyncSession,
    start_date: date,
    end_date: date,
    stock_codes: list[str] | None = None,
    dry_run: bool = False,
    max_per_stock: int = 1000,
) -> dict:
    """뉴스를 기간별로 백필한다.

    네이버 뉴스 검색 API를 사용하여 페이지네이션 처리하며,
    rate limiting (초당 10건 제한)을 준수한다.

    Args:
        session: DB 세션
        start_date: 수집 시작일
        end_date: 수집 종료일
        stock_codes: 대상 종목코드 (None이면 활성 종목 전체)
        dry_run: True이면 수집 대상 건수만 반환
        max_per_stock: 종목당 최대 수집 건수

    Returns:
        수집 결과 요약 dict
    """
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

    total_days = (end_date - start_date).days + 1

    if dry_run:
        return {
            "stock_codes": [s.stock_code for s in stocks],
            "total_days": total_days,
            "fetched": 0,
            "saved": 0,
            "skipped": 0,
        }

    total_fetched = 0
    total_saved = 0
    total_skipped = 0

    for stock in stocks:
        page_size = 100  # 네이버 API 최대
        fetched_for_stock = 0

        # 페이지네이션으로 최대 max_per_stock건 수집
        for start_idx in range(1, max_per_stock + 1, page_size):
            try:
                items = await fetch_news(stock.stock_name, limit=min(page_size, max_per_stock - fetched_for_stock))
            except Exception:
                logger.exception("뉴스 백필 API 호출 실패: %s", stock.stock_code)
                break

            if not items:
                break

            saved_in_page = 0
            skipped_in_page = 0

            for item in items:
                link = (item.get("link") or "").strip()
                if not link:
                    continue

                # 날짜 필터링
                pub_dt = _parse_published_at(item.get("pubDate"))
                pub_date = pub_dt.date() if isinstance(pub_dt, datetime) else pub_dt
                if pub_date < start_date or pub_date > end_date:
                    skipped_in_page += 1
                    continue

                external_id = _build_external_id(stock.stock_code, link)

                existing = await session.execute(
                    select(News.id).where(News.external_id == external_id)
                )
                if existing.scalar_one_or_none() is not None:
                    skipped_in_page += 1
                    continue

                news = News(
                    stock_code=stock.stock_code,
                    stock_name=stock.stock_name,
                    title=(item.get("title") or "").strip(),
                    description=(item.get("description") or "").strip() or None,
                    link=link,
                    external_id=external_id,
                    published_at=pub_dt,
                    summary=None,
                    useful=None,
                )
                session.add(news)
                saved_in_page += 1

            if saved_in_page > 0:
                await session.commit()

            fetched_for_stock += len(items)
            total_fetched += len(items)
            total_saved += saved_in_page
            total_skipped += skipped_in_page

            # Rate limiting (초당 10건 제한 준수)
            await asyncio.sleep(0.15)

            # 더 이상 결과가 없으면 중단
            if len(items) < page_size:
                break

        logger.info(
            "뉴스 백필 완료: %s (%s) fetched=%d",
            stock.stock_name, stock.stock_code, fetched_for_stock,
        )

    return {
        "stock_codes": [s.stock_code for s in stocks],
        "total_days": total_days,
        "fetched": total_fetched,
        "saved": total_saved,
        "skipped": total_skipped,
    }


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

    # 뉴스 수집 후 클러스터 감지
    try:
        from app.services.news_clustering import detect_news_clusters
        detected = await detect_news_clusters(session)
        if detected:
            logger.info("뉴스 클러스터 %d건 감지", len(detected))
    except Exception:
        logger.exception("뉴스 클러스터 감지 실패")

    return results
