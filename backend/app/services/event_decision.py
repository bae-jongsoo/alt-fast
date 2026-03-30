"""이벤트 기반 LLM 매매 판단 서비스.

이벤트 컨텍스트 + 거시 데이터 + 관련 뉴스를 LLM 프롬프트에 포함하여
매수/관망 판단을 받는 모듈. 기존 trader.py의 프롬프트 구조를 참고하되,
이벤트 드리븐에 맞게 재설계.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jinja2 import BaseLoader, Environment
from sqlalchemy import desc, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.macro_snapshot import MacroSnapshot
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.news import News
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.models.prompt_template import PromptTemplate
from app.models.trading_event import TradingEvent
from app.schemas.event_decision import EventDecisionResponse
from app.shared.json_helpers import parse_llm_json_object
from app.shared.llm import ask_llm_by_level, get_llm_level

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
_jinja_env = Environment(loader=BaseLoader(), keep_trailing_newline=True)


# ---------------------------------------------------------------------------
# 프롬프트 빌드
# ---------------------------------------------------------------------------


async def build_event_prompt(
    db: AsyncSession,
    event: TradingEvent,
    strategy_id: int,
) -> str:
    """이벤트 컨텍스트를 수집하여 프롬프트 조합."""
    template = await _get_prompt_template(db, strategy_id, "event_buy")
    if template is None:
        raise ValueError(f"활성 event_buy 프롬프트 템플릿이 없습니다 (strategy_id={strategy_id})")

    now = datetime.now()
    stock_code = event.stock_code
    stock_name = event.stock_name

    # 1. 이벤트 정보
    event_info = {
        "event_type": event.event_type,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "event_data": event.event_data or {},
        "confidence_hint": float(event.confidence_hint) if event.confidence_hint else None,
        "detected_at": _to_iso(event.detected_at),
    }

    # 2. 종목 기본 정보 (MarketSnapshot)
    fundamental = await _get_fundamental(db, stock_code)

    # 3. 거시 데이터 (MacroSnapshot — 당일 최신)
    macro = await _get_macro_snapshot(db)

    # 4. 관련 뉴스 (최대 5건)
    news_items = await _get_recent_news(db, stock_code, now, limit=5)

    # 5. 관련 공시 (최대 3건)
    disclosures = await _get_recent_disclosures(db, stock_code, now, limit=3)

    # 6. 가격 데이터: 최근 30분봉
    candles = await _get_recent_candles(db, stock_code, limit=30)

    # 7. 호가 정보
    orderbook = await _get_latest_orderbook(db, stock_code)

    # 8. 현재 포트폴리오
    portfolio = await _get_portfolio_summary(db, strategy_id)

    context = {
        "current_time": now.isoformat(),
        "event": event_info,
        "fundamental": fundamental,
        "macro": macro,
        "news": news_items,
        "disclosures": disclosures,
        "candles": candles,
        "orderbook": orderbook,
        "portfolio": portfolio,
    }

    context_json = json.dumps(context, ensure_ascii=False, default=_json_default, indent=2)

    return _jinja_env.from_string(template.content).render(
        current_time=now.isoformat(),
        event_type=event.event_type,
        stock_code=stock_code,
        stock_name=stock_name,
        context_json=context_json,
    )


# ---------------------------------------------------------------------------
# LLM 판단
# ---------------------------------------------------------------------------


async def make_event_decision(
    db: AsyncSession,
    event: TradingEvent,
    strategy_id: int,
) -> tuple[EventDecisionResponse, DecisionHistory]:
    """
    1. build_event_prompt()
    2. ask_llm_by_level() 호출
    3. 응답 파싱 (JSON -> EventDecisionResponse)
    4. DecisionHistory 기록
    5. TradingEvent status 업데이트 -> "sent_to_llm" -> "decided"
    """
    started_at = time.monotonic()
    request_payload = ""
    response_payload = ""
    is_error = False
    error_message: str | None = None
    event_response: EventDecisionResponse | None = None
    parsed_decision: dict = {"decision": {"result": "HOLD"}}

    try:
        # 1. 프롬프트 빌드
        request_payload = await build_event_prompt(db, event, strategy_id)

        # 상태 업데이트: sent_to_llm
        event.status = "sent_to_llm"
        await db.flush()

        # 2. LLM 호출
        level = await get_llm_level("llm_event_trading", "high")
        response_payload = await ask_llm_by_level(level, request_payload)

        # 3. 응답 파싱
        event_response = parse_event_decision(response_payload)

        parsed_decision = {
            "decision": {
                "result": event_response.decision,
                "stock_code": event.stock_code,
                "stock_name": event.stock_name,
                "confidence": event_response.confidence,
                "target_return_pct": event_response.target_return_pct,
                "stop_pct": event_response.stop_pct,
                "holding_days": event_response.holding_days,
            },
            "reasoning": event_response.reasoning,
            "event_assessment": event_response.event_assessment,
            "risk_factors": event_response.risk_factors,
        }

    except Exception as exc:
        is_error = True
        error_message = str(exc) or exc.__class__.__name__
        parsed_decision = {"decision": {"result": "HOLD"}}
        # 파싱 실패 시 기본값
        event_response = EventDecisionResponse(
            decision="HOLD",
            confidence=0.0,
            reasoning=f"파싱/LLM 오류: {error_message}",
            target_return_pct=None,
            stop_pct=None,
            holding_days=None,
            event_assessment="",
            risk_factors=[],
        )

    # 4. DecisionHistory 기록
    processing_time_ms = int((time.monotonic() - started_at) * 1000)
    result_str = event_response.decision if event_response else "HOLD"

    history = DecisionHistory(
        strategy_id=strategy_id,
        stock_code=event.stock_code,
        stock_name=event.stock_name,
        decision=result_str,
        request_payload=request_payload,
        response_payload=response_payload,
        parsed_decision=parsed_decision,
        processing_time_ms=max(processing_time_ms, 0),
        is_error=is_error,
        error_message=error_message,
    )
    db.add(history)
    await db.flush()

    # 5. TradingEvent 상태 업데이트
    event.status = "decided"
    event.decision_history_id = history.id
    event.processed_at = datetime.now()
    await db.flush()

    logger.info(
        "이벤트 판단 기록: history_id=%s event_id=%s result=%s confidence=%s",
        history.id,
        event.id,
        result_str,
        event_response.confidence if event_response else 0,
    )

    return event_response, history


# ---------------------------------------------------------------------------
# LLM 응답 파싱
# ---------------------------------------------------------------------------


def parse_event_decision(raw_response: str) -> EventDecisionResponse:
    """LLM 응답을 파싱하여 EventDecisionResponse로 변환."""
    payload = parse_llm_json_object(raw_response)

    # decision 추출
    raw_decision = payload.get("decision", "HOLD")
    if isinstance(raw_decision, dict):
        raw_decision = raw_decision.get("result", "HOLD")
    decision = str(raw_decision).strip().upper()
    if decision not in {"BUY", "HOLD"}:
        decision = "HOLD"

    # confidence 추출
    confidence = _coerce_float(payload.get("confidence"), default=0.0)
    if confidence < 0.0 or confidence > 1.0:
        confidence = max(0.0, min(1.0, confidence))

    # reasoning
    reasoning = str(payload.get("reasoning", ""))

    # target_return_pct
    target_return_pct = _coerce_float(payload.get("target_return_pct"))

    # stop_pct
    stop_pct = _coerce_float(payload.get("stop_pct"))

    # holding_days
    raw_holding = payload.get("holding_days")
    holding_days: int | None = None
    if raw_holding is not None:
        try:
            holding_days = int(raw_holding)
        except (ValueError, TypeError):
            holding_days = None

    # event_assessment
    event_assessment = str(payload.get("event_assessment", ""))

    # risk_factors
    raw_risks = payload.get("risk_factors", [])
    risk_factors: list[str] = []
    if isinstance(raw_risks, list):
        risk_factors = [str(r) for r in raw_risks]

    return EventDecisionResponse(
        decision=decision,  # type: ignore[arg-type]
        confidence=confidence,
        reasoning=reasoning,
        target_return_pct=target_return_pct,
        stop_pct=stop_pct,
        holding_days=holding_days,
        event_assessment=event_assessment,
        risk_factors=risk_factors,
    )


# ---------------------------------------------------------------------------
# 데이터 수집 헬퍼
# ---------------------------------------------------------------------------


async def _get_prompt_template(
    db: AsyncSession, strategy_id: int, prompt_type: str
) -> PromptTemplate | None:
    """DB에서 활성화된 프롬프트 템플릿을 읽는다."""
    result = await db.execute(
        select(PromptTemplate)
        .where(
            PromptTemplate.strategy_id == strategy_id,
            PromptTemplate.prompt_type == prompt_type,
            PromptTemplate.is_active.is_(True),
        )
        .order_by(desc(PromptTemplate.version))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_fundamental(db: AsyncSession, stock_code: str) -> dict:
    """종목 기본 정보 (MarketSnapshot)."""
    result = await db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.stock_code == stock_code)
        .order_by(desc(MarketSnapshot.published_at), desc(MarketSnapshot.created_at))
        .limit(1)
    )
    ms = result.scalar_one_or_none()
    if ms is None:
        return {}
    return {
        "collected_at": _to_iso(ms.published_at or ms.created_at),
        "per": _safe_float(ms.per),
        "pbr": _safe_float(ms.pbr),
        "eps": _safe_float(ms.eps),
        "bps": _safe_float(ms.bps),
        "hts_avls": ms.hts_avls,
        "w52_hgpr": ms.w52_hgpr,
        "w52_lwpr": ms.w52_lwpr,
        "hts_frgn_ehrt": _safe_float(ms.hts_frgn_ehrt),
        "vol_tnrt": _safe_float(ms.vol_tnrt),
    }


async def _get_macro_snapshot(db: AsyncSession) -> dict:
    """당일 최신 거시 데이터."""
    result = await db.execute(
        select(MacroSnapshot)
        .order_by(desc(MacroSnapshot.snapshot_date))
        .limit(1)
    )
    macro = result.scalar_one_or_none()
    if macro is None:
        return {}
    return {
        "snapshot_date": str(macro.snapshot_date),
        "sp500_close": _safe_float(macro.sp500_close),
        "sp500_change_pct": _safe_float(macro.sp500_change_pct),
        "nasdaq_close": _safe_float(macro.nasdaq_close),
        "nasdaq_change_pct": _safe_float(macro.nasdaq_change_pct),
        "vix": _safe_float(macro.vix),
        "us_10y_treasury": _safe_float(macro.us_10y_treasury),
        "usd_krw": _safe_float(macro.usd_krw),
        "usd_krw_change_pct": _safe_float(macro.usd_krw_change_pct),
        "gold": _safe_float(macro.gold),
        "wti": _safe_float(macro.wti),
        "sox_close": _safe_float(macro.sox_close),
        "sox_change_pct": _safe_float(macro.sox_change_pct),
    }


async def _get_recent_news(
    db: AsyncSession, stock_code: str, now: datetime, limit: int = 5
) -> list[dict]:
    """해당 종목 최근 뉴스."""
    result = await db.execute(
        select(News)
        .where(News.stock_code == stock_code)
        .where(or_(News.useful.is_(True), News.useful.is_(None)))
        .order_by(desc(News.published_at), desc(News.created_at))
        .limit(limit)
    )
    return [
        {
            "title": n.title,
            "summary": n.summary,
            "published_at": _to_iso(n.published_at),
        }
        for n in result.scalars().all()
    ]


async def _get_recent_disclosures(
    db: AsyncSession, stock_code: str, now: datetime, limit: int = 3
) -> list[dict]:
    """해당 종목 최근 공시."""
    result = await db.execute(
        select(DartDisclosure)
        .where(DartDisclosure.stock_code == stock_code)
        .where(DartDisclosure.published_at >= now - timedelta(days=7))
        .where(DartDisclosure.published_at <= now)
        .order_by(desc(DartDisclosure.published_at), desc(DartDisclosure.created_at))
        .limit(limit)
    )
    return [
        {
            "title": d.title,
            "description": d.description,
            "published_at": _to_iso(d.published_at),
        }
        for d in result.scalars().all()
    ]


async def _get_recent_candles(
    db: AsyncSession, stock_code: str, limit: int = 30
) -> list[dict]:
    """최근 분봉 데이터."""
    result = await db.execute(
        select(MinuteCandle)
        .where(MinuteCandle.stock_code == stock_code)
        .order_by(desc(MinuteCandle.minute_at))
        .limit(limit)
    )
    candles = list(result.scalars().all())
    candles.reverse()  # 시간 순서로 정렬
    return [
        {
            "minute_at": _to_iso(c.minute_at),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


async def _get_latest_orderbook(db: AsyncSession, stock_code: str) -> dict | None:
    """최신 호가 스냅샷."""
    result = await db.execute(
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.stock_code == stock_code)
        .order_by(desc(OrderbookSnapshot.snapshot_at))
        .limit(1)
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        return None
    return {
        "snapshot_at": _to_iso(ob.snapshot_at),
        "asks": [
            {"price": getattr(ob, f"ask_price{i}"), "volume": getattr(ob, f"ask_volume{i}")}
            for i in range(1, 6)
        ],
        "bids": [
            {"price": getattr(ob, f"bid_price{i}"), "volume": getattr(ob, f"bid_volume{i}")}
            for i in range(1, 6)
        ],
        "total_ask_volume": ob.total_ask_volume,
        "total_bid_volume": ob.total_bid_volume,
    }


async def _get_portfolio_summary(db: AsyncSession, strategy_id: int) -> dict:
    """현재 포트폴리오 요약."""
    # 현금
    cash_result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code.is_(None),
        )
    )
    cash_row = cash_result.scalar_one_or_none()
    cash_amount = float(cash_row.total_amount) if cash_row else 0.0

    # 보유 포지션
    position_result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code.isnot(None),
        )
    )
    positions = list(position_result.scalars().all())

    return {
        "cash": cash_amount,
        "positions": [
            {
                "stock_code": p.stock_code,
                "stock_name": p.stock_name,
                "quantity": p.quantity,
                "unit_price": float(p.unit_price),
                "total_amount": float(p.total_amount),
            }
            for p in positions
        ],
    }


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _safe_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _coerce_float(value, default: float | None = None) -> float | None:
    """값을 float으로 변환. 실패 시 default 반환."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return _to_iso(value) or ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
