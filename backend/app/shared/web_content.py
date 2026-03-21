"""기사 본문 크롤링."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

import httpx


async def extract_article_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()

    parser = _ArticleHTMLParser()
    parser.feed(response.text)
    parser.close()
    text = parser.get_text()
    if not text:
        raise ValueError("기사 본문 추출 실패")
    return text


class _ArticleHTMLParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe"}
    _PRIORITY_TAGS = {"article", "main"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._priority_depth = 0
        self._priority_chunks: list[str] = []
        self._body_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self._PRIORITY_TAGS:
            self._priority_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in self._PRIORITY_TAGS and self._priority_depth > 0:
            self._priority_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._priority_depth > 0:
            self._priority_chunks.append(text)
        self._body_chunks.append(text)

    def get_text(self) -> str:
        chunks = self._priority_chunks or self._body_chunks
        joined = " ".join(chunks)
        joined = unescape(joined)
        joined = re.sub(r"\s+", " ", joined)
        return joined.strip()
