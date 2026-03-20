from __future__ import annotations

import re
from html import unescape

import httpx

from app.config import settings

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    clean = _HTML_TAG_PATTERN.sub(" ", text)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


async def fetch_news(stock_name: str, limit: int = 10) -> list[dict]:
    """네이버 뉴스 API로 종목 관련 뉴스를 검색한다."""
    query = f"{stock_name} 주식"

    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(
            NAVER_NEWS_API_URL,
            headers={
                "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
            },
            params={
                "query": query,
                "display": limit,
                "sort": "date",
            },
        )
        response.raise_for_status()

    payload = response.json()
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("네이버 API 비정상 응답: items 필드가 없습니다")

    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        link = (item.get("link") or item.get("originallink") or "").strip()
        normalized.append({
            "title": _strip_html(item.get("title") or ""),
            "link": link,
            "description": _strip_html(item.get("description") or ""),
            "pubDate": item.get("pubDate") or "",
        })
    return normalized
