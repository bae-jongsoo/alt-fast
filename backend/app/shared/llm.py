"""Gemini LLM 호출 (OpenAI 호환 모드)."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _client


async def ask_llm(prompt: str) -> str:
    """프롬프트를 Gemini에 보내고 전체 응답 텍스트를 반환한다."""
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.GEMINI_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.choices[0].message.content
    return content or ""
