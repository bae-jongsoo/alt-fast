"""챗봇 서비스 — OpenAI LLM 연동 + Function Calling + SSE 스트리밍."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import AsyncGenerator

from openai import AsyncOpenAI
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.asset import Asset
from app.models.order_history import OrderHistory
from app.models.decision_history import DecisionHistory
from app.models.market_snapshot import MarketSnapshot
from app.models.news import News
from app.models.dart_disclosure import DartDisclosure
from app.models.minute_candle import MinuteCandle

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "당신은 ALT 한국 주식 자동매매 시스템의 AI 어시스턴트입니다.\n"
    "사용자의 질문에 대해 시스템에 저장된 데이터를 조회하여 정확하게 답변합니다.\n"
    "답변은 한국어로 하며, 마크다운 형식을 사용할 수 있습니다.\n"
    "금액은 원 단위로, 수익률은 %로 표시합니다.\n\n"
    '차트나 그래프 표시 요청을 받으면 다음과 같이 안내하세요:\n'
    '"현재 차트 표시는 지원되지 않습니다. 대신 최근 분봉 데이터를 텍스트로 안내드립니다."\n'
    "그 후 해당 데이터를 마크다운 테이블 형태로 제공하세요."
)

# ---------------------------------------------------------------------------
# OpenAI Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_assets",
            "description": "현재 보유 자산 조회 (현금 + 보유종목)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_history",
            "description": "매매 주문 이력 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드 (예: 005930). 없으면 전체 조회.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "시작일 (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료일 (YYYY-MM-DD)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 조회 건수 (기본 20)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_decision_history",
            "description": "LLM 판단 이력 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드 (예: 005930). 없으면 전체 조회.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "시작일 (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료일 (YYYY-MM-DD)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 조회 건수 (기본 20)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_snapshot",
            "description": "종목 최신 시장 정보 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드 (예: 005930)",
                    },
                },
                "required": ["stock_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "뉴스 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드. 없으면 전체 조회.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "시작일 (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료일 (YYYY-MM-DD)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 조회 건수 (기본 10)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dart_disclosures",
            "description": "DART 공시 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드. 없으면 전체 조회.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "시작일 (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "종료일 (YYYY-MM-DD)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 조회 건수 (기본 10)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_minute_candles",
            "description": "분봉 데이터 조회",
            "parameters": {
                "type": "object",
                "properties": {
                    "stock_code": {
                        "type": "string",
                        "description": "종목코드 (예: 005930)",
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "시작 일시 (YYYY-MM-DD HH:MM:SS)",
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "종료 일시 (YYYY-MM-DD HH:MM:SS)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "최대 조회 건수 (기본 60)",
                    },
                },
                "required": ["stock_code"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _dt(v: str | None, fmt: str = "%Y-%m-%d") -> datetime | None:
    if v is None:
        return None
    return datetime.strptime(v, fmt)


def _serialize(obj: object) -> str:
    """datetime / Decimal 등을 JSON-safe 문자열로 변환."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


async def get_assets() -> dict:
    """현재 보유 자산 조회 (현금 + 보유종목)."""
    async with async_session() as db:
        result = await db.execute(select(Asset).order_by(Asset.updated_at.desc()))
        rows = result.scalars().all()
        items = []
        for r in rows:
            items.append(
                {
                    "stock_code": r.stock_code,
                    "stock_name": r.stock_name,
                    "quantity": r.quantity,
                    "unit_price": float(r.unit_price),
                    "total_amount": float(r.total_amount),
                    "updated_at": _serialize(r.updated_at),
                }
            )
        return {"assets": items, "count": len(items)}


async def get_order_history(
    stock_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """매매 주문 이력 조회."""
    async with async_session() as db:
        stmt = select(OrderHistory).order_by(desc(OrderHistory.created_at)).limit(limit)
        if stock_code:
            stmt = stmt.where(OrderHistory.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(OrderHistory.created_at >= _dt(start_date))
        if end_date:
            stmt = stmt.where(OrderHistory.created_at <= _dt(end_date, "%Y-%m-%d"))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "order_type": r.order_type,
                "order_price": float(r.order_price),
                "order_quantity": r.order_quantity,
                "order_total_amount": float(r.order_total_amount),
                "result_price": float(r.result_price),
                "result_quantity": r.result_quantity,
                "result_total_amount": float(r.result_total_amount),
                "profit_loss": float(r.profit_loss) if r.profit_loss is not None else None,
                "profit_rate": r.profit_rate,
                "order_placed_at": _serialize(r.order_placed_at),
                "created_at": _serialize(r.created_at),
            }
            for r in rows
        ]


async def get_decision_history(
    stock_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """LLM 판단 이력 조회."""
    async with async_session() as db:
        stmt = select(DecisionHistory).order_by(desc(DecisionHistory.created_at)).limit(limit)
        if stock_code:
            stmt = stmt.where(DecisionHistory.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(DecisionHistory.created_at >= _dt(start_date))
        if end_date:
            stmt = stmt.where(DecisionHistory.created_at <= _dt(end_date, "%Y-%m-%d"))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "decision": r.decision,
                "parsed_decision": r.parsed_decision,
                "processing_time_ms": r.processing_time_ms,
                "is_error": r.is_error,
                "created_at": _serialize(r.created_at),
            }
            for r in rows
        ]


async def get_market_snapshot(stock_code: str) -> dict | None:
    """종목 최신 시장 정보 조회."""
    async with async_session() as db:
        stmt = (
            select(MarketSnapshot)
            .where(MarketSnapshot.stock_code == stock_code)
            .order_by(desc(MarketSnapshot.created_at))
            .limit(1)
        )
        result = await db.execute(stmt)
        r = result.scalar_one_or_none()
        if r is None:
            return None
        return {
            "stock_code": r.stock_code,
            "stock_name": r.stock_name,
            "per": float(r.per) if r.per else None,
            "pbr": float(r.pbr) if r.pbr else None,
            "eps": float(r.eps) if r.eps else None,
            "bps": float(r.bps) if r.bps else None,
            "hts_avls": r.hts_avls,
            "w52_hgpr": r.w52_hgpr,
            "w52_lwpr": r.w52_lwpr,
            "hts_frgn_ehrt": float(r.hts_frgn_ehrt) if r.hts_frgn_ehrt else None,
            "vol_tnrt": float(r.vol_tnrt) if r.vol_tnrt else None,
            "published_at": _serialize(r.published_at) if r.published_at else None,
            "created_at": _serialize(r.created_at),
        }


async def get_news(
    stock_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """뉴스 조회."""
    async with async_session() as db:
        stmt = select(News).order_by(desc(News.created_at)).limit(limit)
        if stock_code:
            stmt = stmt.where(News.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(News.created_at >= _dt(start_date))
        if end_date:
            stmt = stmt.where(News.created_at <= _dt(end_date, "%Y-%m-%d"))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "title": r.title,
                "summary": r.summary,
                "link": r.link,
                "published_at": _serialize(r.published_at) if r.published_at else None,
                "created_at": _serialize(r.created_at),
            }
            for r in rows
        ]


async def get_dart_disclosures(
    stock_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """DART 공시 조회."""
    async with async_session() as db:
        stmt = select(DartDisclosure).order_by(desc(DartDisclosure.created_at)).limit(limit)
        if stock_code:
            stmt = stmt.where(DartDisclosure.stock_code == stock_code)
        if start_date:
            stmt = stmt.where(DartDisclosure.created_at >= _dt(start_date))
        if end_date:
            stmt = stmt.where(DartDisclosure.created_at <= _dt(end_date, "%Y-%m-%d"))
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "title": r.title,
                "link": r.link,
                "description": r.description,
                "published_at": _serialize(r.published_at) if r.published_at else None,
                "created_at": _serialize(r.created_at),
            }
            for r in rows
        ]


async def get_minute_candles(
    stock_code: str,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    limit: int = 60,
) -> list[dict]:
    """분봉 데이터 조회."""
    async with async_session() as db:
        stmt = (
            select(MinuteCandle)
            .where(MinuteCandle.stock_code == stock_code)
            .order_by(desc(MinuteCandle.minute_at))
            .limit(limit)
        )
        if start_datetime:
            stmt = stmt.where(
                MinuteCandle.minute_at >= _dt(start_datetime, "%Y-%m-%d %H:%M:%S")
            )
        if end_datetime:
            stmt = stmt.where(
                MinuteCandle.minute_at <= _dt(end_datetime, "%Y-%m-%d %H:%M:%S")
            )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "stock_code": r.stock_code,
                "minute_at": _serialize(r.minute_at),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "get_assets": get_assets,
    "get_order_history": get_order_history,
    "get_decision_history": get_decision_history,
    "get_market_snapshot": get_market_snapshot,
    "get_news": get_news,
    "get_dart_disclosures": get_dart_disclosures,
    "get_minute_candles": get_minute_candles,
}


async def _call_tool(name: str, arguments: dict) -> str:
    """도구를 실행하고 결과를 JSON 문자열로 반환."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
    try:
        result = await func(**arguments)
        return json.dumps(result, ensure_ascii=False, default=_serialize)
    except Exception as e:
        logger.exception("Tool call failed: %s", name)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main chat stream
# ---------------------------------------------------------------------------

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _client


async def chat_stream(
    message: str,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """LLM 기반 챗봇 SSE 스트리밍.

    1. 사용자 질문 수신
    2. 시스템 프롬프트 + 사용자 질문 + 대화 이력을 LLM에 전달
    3. LLM이 tool call을 반환하면 -> 해당 도구 실행 -> 결과를 다시 LLM에 전달
    4. LLM이 최종 답변 생성 -> SSE로 스트리밍 반환
    """
    client = _get_client()
    history = history or []

    # 메시지 구성
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    try:
        # 최대 5회 tool call 루프 (무한루프 방지)
        for _ in range(5):
            response = await client.chat.completions.create(
                model=settings.GEMINI_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            choice = response.choices[0]

            # tool call이 없으면 최종 답변이므로 스트리밍 시작
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                break

            # tool call 처리
            assistant_msg = choice.message
            messages.append(assistant_msg.model_dump())

            for tool_call in assistant_msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                logger.info("Tool call: %s(%s)", fn_name, fn_args)

                tool_result = await _call_tool(fn_name, fn_args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )

        # 최종 응답 스트리밍
        stream = await client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=messages,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                data = json.dumps(
                    {"type": "token", "content": delta.content},
                    ensure_ascii=False,
                )
                yield f"data: {data}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception:
        logger.exception("Chat stream error")
        error_data = json.dumps(
            {"type": "error", "content": "답변을 생성하지 못했습니다."},
            ensure_ascii=False,
        )
        yield f"data: {error_data}\n\n"
