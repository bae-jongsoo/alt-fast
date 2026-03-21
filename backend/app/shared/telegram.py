"""텔레그램 Bot API 메시지 발송."""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_message(message: str, chat_id: str | None = None) -> bool:
    """텔레그램 메시지 발송. 실패 시 False 반환."""
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다")
        return False

    target_chat_id = chat_id or settings.TELEGRAM_CHAT_ID
    if not target_chat_id:
        logger.warning("TELEGRAM_CHAT_ID가 설정되지 않았습니다")
        return False

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": target_chat_id, "text": message},
            )
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error("텔레그램 알림 발송 실패: %s", e)
        return False
