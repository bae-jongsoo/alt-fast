"""LLM 호출 — openclaw / nanobot subprocess."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

logger = logging.getLogger(__name__)

OPENCLAW_BIN = "/Users/jongsoobae/.nvm/versions/node/v24.14.0/bin/openclaw"
NANOBOT_BIN = "/Users/jongsoobae/.local/bin/nanobot"

_AUTH_ERROR_KEYWORDS = ["Token refresh failed", "refresh_token_reused", "401"]
_STDOUT_ERROR_KEYWORDS = ["Error calling", "response failed"]


class LLMAuthError(RuntimeError):
    pass


_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds


async def ask_llm(prompt: str, timeout_seconds: int = 60) -> str:
    """openclaw agent --local로 LLM을 호출하고 응답 텍스트를 반환한다. (gpt-5.2)"""
    session_id = str(uuid.uuid4())

    proc = await asyncio.create_subprocess_exec(
        OPENCLAW_BIN, "agent", "--local",
        "--session-id", session_id,
        "-m", prompt,
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("LLM 호출 타임아웃")

    stdout = (stdout_bytes or b"").decode().strip()
    stderr = (stderr_bytes or b"").decode().strip()

    if proc.returncode != 0:
        message = "LLM 실행이 비정상 종료되었습니다"
        if stderr:
            message = f"{message}: {stderr}"
        if any(kw in stderr for kw in _AUTH_ERROR_KEYWORDS):
            raise LLMAuthError(message)
        raise RuntimeError(message)

    if not stdout:
        raise RuntimeError("LLM 응답이 비어있습니다")

    if any(kw in stdout for kw in _STDOUT_ERROR_KEYWORDS):
        raise RuntimeError(f"LLM 응답에 에러가 포함되어 있습니다: {stdout[:200]}")

    # --json 모드: payloads[0].text에서 텍스트 추출
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            payloads = data.get("payloads")
            if isinstance(payloads, list) and payloads:
                text = payloads[0].get("text", "")
                if text:
                    return text
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return stdout


async def ask_llm_high(prompt: str, timeout_seconds: int = 120) -> str:
    """nanobot agent로 고성능 LLM을 호출한다. (gpt-5.4)"""
    session_id = str(uuid.uuid4())

    proc = await asyncio.create_subprocess_exec(
        NANOBOT_BIN, "agent", "--no-markdown",
        "-s", session_id,
        "-m", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("LLM(high) 호출 타임아웃")

    stdout = (stdout_bytes or b"").decode().strip()
    stderr = (stderr_bytes or b"").decode().strip()

    if proc.returncode != 0:
        message = "LLM(high) 실행이 비정상 종료되었습니다"
        if stderr:
            message = f"{message}: {stderr}"
        if any(kw in stderr for kw in _AUTH_ERROR_KEYWORDS):
            raise LLMAuthError(message)
        raise RuntimeError(message)

    if not stdout:
        raise RuntimeError("LLM(high) 응답이 비어있습니다")

    if any(kw in stdout for kw in _STDOUT_ERROR_KEYWORDS):
        raise RuntimeError(f"LLM(high) 응답에 에러가 포함되어 있습니다: {stdout[:200]}")

    # "🐈 nanobot\n" 접두사 제거
    if stdout.startswith("🐈"):
        lines = stdout.split("\n", 1)
        stdout = lines[1].strip() if len(lines) > 1 else ""

    if not stdout:
        raise RuntimeError("LLM(high) 응답이 비어있습니다")

    return stdout


async def _call_with_retry(fn, prompt: str, timeout_seconds: int, label: str) -> str:
    """LLM 호출을 재시도한다. LLMAuthError는 즉시 전파."""
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await fn(prompt, timeout_seconds=timeout_seconds)
        except LLMAuthError:
            raise
        except Exception as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "%s 호출 실패 (시도 %d/%d), %d초 후 재시도: %s",
                    label, attempt, _MAX_RETRIES, delay, e,
                )
                await asyncio.sleep(delay)
    raise last_error  # type: ignore[misc]


async def ask_llm_by_level(level: str, prompt: str, timeout_seconds: int = 120) -> str:
    """level에 따라 적절한 LLM을 호출한다. (normal/high) — 실패 시 자동 재시도."""
    if level == "high":
        return await _call_with_retry(ask_llm_high, prompt, timeout_seconds, "LLM(high)")
    return await _call_with_retry(ask_llm, prompt, timeout_seconds, "LLM")


async def get_llm_level(param_key: str, default: str = "normal") -> str:
    """DB에서 LLM 레벨 파라미터를 읽는다."""
    from sqlalchemy import select
    from app.database import async_session
    from app.models.system_parameter import SystemParameter

    async with async_session() as db:
        result = await db.execute(
            select(SystemParameter).where(
                SystemParameter.key == param_key,
                SystemParameter.strategy_id.is_(None),
            )
        )
        param = result.scalar_one_or_none()
        return param.value if param else default
