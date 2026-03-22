"""트레이딩 사이클 핵심 로직 — Django → SQLAlchemy async 포팅.

주요 변경:
- Django ORM → SQLAlchemy AsyncSession
- nanobot → Gemini (OpenAI 호환)
- 하드코딩 프롬프트 → DB prompt_templates 테이블에서 읽기
- KIS 실주문 → 가상매수/매도 (DB 숫자만 변경)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.news import News
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.models.target_stock import TargetStock
from app.services.asset_manager import (
    apply_virtual_buy,
    apply_virtual_sell,
    get_cash_asset,
    get_open_position,
)
from app.shared.json_helpers import normalize_trade_decision, parse_llm_json_object
from app.shared.llm import ask_llm_high as ask_llm
from app.shared.telegram import send_message as send_telegram

logger = logging.getLogger(__name__)

DECISION_ALLOWED_RESULTS = {"BUY", "SELL", "HOLD"}
RECENT_TRADE_LOOKBACK_MINUTES = 5


# ---------------------------------------------------------------------------
# 메인 사이클
# ---------------------------------------------------------------------------


async def run_trading_cycle(db: AsyncSession) -> DecisionHistory:
    """트레이딩 사이클 1회 실행.

    1. 포지션 확인 (보유 종목 있으면 SELL 판단, 없으면 BUY 판단)
    2. 프롬프트 조합 (DB prompt_template + 컨텍스트)
    3. LLM 호출
    4. 응답 파싱 + 판단 기록
    5. BUY/SELL이면 가상 주문 실행
    """
    started_at = time.monotonic()
    current_time = datetime.now()
    request_payload = ""
    response_payload = ""
    parsed_decision: dict = {"decision": {"result": "HOLD"}}
    is_error = False
    error_message: str | None = None

    try:
        position = await get_open_position(db)
        if position is None:
            request_payload = await build_buy_prompt(db, current_time)
        else:
            request_payload = await build_sell_prompt(db, position.stock_code, current_time)

        if request_payload is None:
            processing_time_ms = int((time.monotonic() - started_at) * 1000)
            return await record_decision_history(
                db,
                request_payload="",
                response_payload="",
                parsed_decision=parsed_decision,
                processing_time_ms=processing_time_ms,
                is_error=False,
                error_message=None,
            )

        response_payload = await ask_llm(request_payload)
        parsed_payload = parse_llm_json_object(response_payload)
        normalized_decision = normalize_trade_decision(parsed_payload)
        parsed_decision = normalized_decision

        if _has_invalid_result(parsed_payload):
            is_error = True
            error_message = "decision.result 허용값이 아닙니다"
        elif _downgraded_to_hold(parsed_payload, normalized_decision):
            is_error = True
            error_message = "BUY/SELL 주문 필수값이 누락되었거나 유효하지 않습니다"

    except Exception as exc:
        is_error = True
        error_message = str(exc) or exc.__class__.__name__
        parsed_decision = {"decision": {"result": "HOLD"}}

    processing_time_ms = int((time.monotonic() - started_at) * 1000)
    decision_history = await record_decision_history(
        db,
        request_payload=request_payload or "",
        response_payload=response_payload,
        parsed_decision=parsed_decision,
        processing_time_ms=processing_time_ms,
        is_error=is_error,
        error_message=error_message,
    )

    # 텔레그램 알림: 에러 시
    if not request_payload:
        await _alert(f"[트레이더] 데이터 수집 이상 - 프롬프트 생성 실패 (id={decision_history.id})")
    elif not response_payload:
        await _alert(f"[트레이더] LLM 응답 없음 (id={decision_history.id}, error={error_message})")
    elif is_error:
        await _alert(f"[트레이더] 에러 (id={decision_history.id}, error={error_message})")

    decision = parsed_decision.get("decision", {})
    result = decision.get("result")

    if not is_error and result == "BUY":
        await execute_buy(
            db,
            decision_history=decision_history,
            stock_code=str(decision["stock_code"]),
            price=Decimal(str(decision["price"])),
            quantity=int(decision["quantity"]),
        )
    elif not is_error and result == "SELL":
        await execute_sell(
            db,
            decision_history=decision_history,
            stock_code=str(decision["stock_code"]),
            price=Decimal(str(decision["price"])),
            quantity=int(decision["quantity"]),
        )

    await db.commit()
    return decision_history


async def _alert(message: str) -> None:
    """텔레그램 알림 발송 (실패해도 무시)."""
    try:
        await send_telegram(message)
    except Exception:
        logger.exception("텔레그램 알림 발송 실패")


# ---------------------------------------------------------------------------
# 프롬프트 빌드
# ---------------------------------------------------------------------------


async def build_buy_prompt(
    db: AsyncSession, current_time: datetime
) -> str | None:
    """매수 프롬프트 조합: DB에서 prompt_template(type='buy') 읽기 + 변수 치환."""
    template = await _get_prompt_template(db, "buy")
    if template is None:
        logger.warning("활성화된 buy 프롬프트 템플릿이 없습니다")
        return None

    cash = await get_cash_asset(db)
    target_stocks = await _get_target_stocks(db)

    stock_contexts = []
    for ts in target_stocks:
        ctx = await _build_stock_prompt_context(db, ts.stock_code, ts.stock_name, current_time)
        if ctx is not None:
            stock_contexts.append(ctx)

    if not stock_contexts:
        return None

    stock_contexts_json = json.dumps(stock_contexts, ensure_ascii=False, default=_json_default, indent=2)

    # 최근 거래이력 (왕복매매 방지용)
    recent_trades = await _get_recent_trades(db, current_time)
    recent_trades_block = ""
    if recent_trades:
        recent_trades_json = json.dumps(recent_trades, ensure_ascii=False, default=_json_default, indent=2)
        recent_trades_block = (
            f"\n<최근거래이력>\n"
            f"{recent_trades_json}\n"
            f"</최근거래이력>\n"
            f"- 위 거래는 최근 {RECENT_TRADE_LOOKBACK_MINUTES}분 내 체결된 내역입니다. "
            "동일 종목을 같은 근거로 재매수하는 것은 왕복 매매이므로 피하세요.\n"
            "  새로운 모멘텀이나 명확히 다른 진입 근거가 없다면 해당 종목은 HOLD하세요.\n"
        )

    prompt = template.content.format(
        current_time=current_time.isoformat(),
        cash_amount=cash.total_amount,
        stock_contexts=stock_contexts_json,
    )
    return prompt + recent_trades_block


async def build_sell_prompt(
    db: AsyncSession, stock_code: str, current_time: datetime
) -> str | None:
    """매도 프롬프트 조합: DB에서 prompt_template(type='sell') 읽기 + 변수 치환."""
    template = await _get_prompt_template(db, "sell")
    if template is None:
        logger.warning("활성화된 sell 프롬프트 템플릿이 없습니다")
        return None

    position = await get_open_position(db)
    if position is None or position.stock_code != stock_code:
        raise ValueError("보유 종목이 아니거나 미보유 상태입니다")

    stock_name = position.stock_name or ""
    target_stock = await _get_target_stock(db, stock_code)
    if target_stock and target_stock.stock_name:
        stock_name = target_stock.stock_name

    stock_context = await _build_stock_prompt_context(db, stock_code, stock_name, current_time)
    if stock_context is None:
        return None

    buy_reason = await _get_buy_reason(db, stock_code)
    stock_context_json = json.dumps(stock_context, ensure_ascii=False, default=_json_default, indent=2)

    prompt = template.content.format(
        current_time=current_time.isoformat(),
        stock_code=stock_code,
        stock_name=stock_name,
        quantity=position.quantity,
        avg_buy_price=position.unit_price,
        buy_reason=buy_reason or "",
        stock_contexts=stock_context_json,
    )
    return prompt


# ---------------------------------------------------------------------------
# 판단 기록
# ---------------------------------------------------------------------------


async def record_decision_history(
    db: AsyncSession,
    request_payload: str,
    response_payload: str,
    parsed_decision: dict,
    processing_time_ms: int,
    is_error: bool,
    error_message: str | None,
) -> DecisionHistory:
    """decision_histories에 판단 결과를 기록한다."""
    result = _extract_result(parsed_decision)
    if result not in DECISION_ALLOWED_RESULTS:
        raise ValueError("result 허용값은 BUY, SELL, HOLD 입니다")

    decision_info = parsed_decision.get("decision", {})
    stock_code = str(decision_info.get("stock_code") or "")
    stock_name = str(decision_info.get("stock_name") or "")

    history = DecisionHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        decision=result,
        request_payload=request_payload,
        response_payload=response_payload,
        parsed_decision=parsed_decision,
        processing_time_ms=max(processing_time_ms, 0),
        is_error=is_error,
        error_message=error_message,
    )
    db.add(history)
    await db.flush()

    logger.info(
        "판단 기록: id=%s result=%s stock_code=%s processing_time_ms=%s error=%s",
        history.id, result, stock_code, processing_time_ms, error_message,
    )
    return history


# ---------------------------------------------------------------------------
# 주문 실행
# ---------------------------------------------------------------------------


async def execute_buy(
    db: AsyncSession,
    decision_history: DecisionHistory,
    stock_code: str,
    price: Decimal,
    quantity: int,
) -> OrderHistory:
    """가상 매수 실행: apply_virtual_buy + order_histories 기록."""
    if decision_history.decision != "BUY":
        raise ValueError("BUY 판단이 아니면 매수 주문을 실행할 수 없습니다")
    _validate_positive_order(price=price, quantity=quantity)

    position = await get_open_position(db)
    if position is not None:
        raise ValueError("이미 보유 종목이 있어 매수 불가합니다")

    # 종목명 조회
    target_stock = await _get_target_stock(db, stock_code)
    stock_name = target_stock.stock_name if target_stock else ""

    order_total_amount = price * quantity
    executed_at = datetime.now()

    await apply_virtual_buy(db, stock_code, stock_name, price, quantity)

    order = OrderHistory(
        decision_history_id=decision_history.id,
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="BUY",
        order_price=float(price),
        order_quantity=quantity,
        order_total_amount=float(order_total_amount),
        result_price=float(price),
        result_quantity=quantity,
        result_total_amount=float(order_total_amount),
        order_placed_at=executed_at,
        result_executed_at=executed_at,
    )
    db.add(order)
    await db.flush()

    logger.info(
        "매수 실행: order_id=%s stock=%s price=%s qty=%s total=%s",
        order.id, stock_code, price, quantity, order_total_amount,
    )
    return order


async def execute_sell(
    db: AsyncSession,
    decision_history: DecisionHistory,
    stock_code: str,
    price: Decimal,
    quantity: int,
) -> OrderHistory:
    """가상 매도 실행: apply_virtual_sell + order_histories 기록 + 손익 계산."""
    if decision_history.decision != "SELL":
        raise ValueError("SELL 판단이 아니면 매도 주문을 실행할 수 없습니다")
    _validate_positive_order(price=price, quantity=quantity)

    position = await get_open_position(db)
    if position is None or position.stock_code != stock_code:
        raise ValueError("해당 종목을 보유하고 있지 않은 미보유 상태입니다")
    if quantity > position.quantity:
        raise ValueError("보유 수량을 초과해 매도할 수 없습니다")

    stock_name = position.stock_name or ""
    avg_buy_price = Decimal(str(position.unit_price))
    order_total_amount = price * quantity
    profit_loss = (price - avg_buy_price) * quantity
    profit_rate = float((price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0.0
    executed_at = datetime.now()

    await apply_virtual_sell(db, stock_code, price, quantity)

    order = OrderHistory(
        decision_history_id=decision_history.id,
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="SELL",
        order_price=float(price),
        order_quantity=quantity,
        order_total_amount=float(order_total_amount),
        result_price=float(price),
        result_quantity=quantity,
        result_total_amount=float(order_total_amount),
        profit_loss=float(profit_loss),
        profit_rate=profit_rate,
        order_placed_at=executed_at,
        result_executed_at=executed_at,
    )
    db.add(order)
    await db.flush()

    logger.info(
        "매도 실행: order_id=%s stock=%s price=%s qty=%s total=%s profit_loss=%s",
        order.id, stock_code, price, quantity, order_total_amount, profit_loss,
    )
    return order


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


async def _get_prompt_template(db: AsyncSession, prompt_type: str) -> PromptTemplate | None:
    """DB에서 활성화된 프롬프트 템플릿을 읽는다."""
    result = await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.prompt_type == prompt_type)
        .where(PromptTemplate.is_active.is_(True))
        .order_by(desc(PromptTemplate.version))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_target_stocks(db: AsyncSession) -> list[TargetStock]:
    """활성화된 대상 종목 목록을 반환한다."""
    result = await db.execute(
        select(TargetStock).where(TargetStock.is_active.is_(True))
    )
    return list(result.scalars().all())


async def _get_target_stock(db: AsyncSession, stock_code: str) -> TargetStock | None:
    """종목코드로 대상 종목을 조회한다."""
    result = await db.execute(
        select(TargetStock).where(TargetStock.stock_code == stock_code).limit(1)
    )
    return result.scalar_one_or_none()


async def _build_stock_prompt_context(
    db: AsyncSession, stock_code: str, stock_name: str, now: datetime
) -> dict | None:
    """종목별 시장 데이터, 뉴스, 공시, 분봉 등 프롬프트 컨텍스트를 조합한다."""
    # 시장 스냅샷
    ms_result = await db.execute(
        select(MarketSnapshot)
        .where(MarketSnapshot.stock_code == stock_code)
        .order_by(desc(MarketSnapshot.published_at), desc(MarketSnapshot.created_at))
        .limit(1)
    )
    market_snapshot = ms_result.scalar_one_or_none()

    # DART 공시 (최근 7일)
    dart_result = await db.execute(
        select(DartDisclosure)
        .where(DartDisclosure.stock_code == stock_code)
        .where(DartDisclosure.published_at >= now - timedelta(days=7))
        .where(DartDisclosure.published_at <= now)
        .order_by(desc(DartDisclosure.published_at), desc(DartDisclosure.created_at))
    )
    disclosures = list(dart_result.scalars().all())

    # 뉴스 (useful=True 또는 NULL, 최근 10건)
    news_result = await db.execute(
        select(News)
        .where(News.stock_code == stock_code)
        .where(or_(News.useful.is_(True), News.useful.is_(None)))
        .order_by(desc(News.published_at), desc(News.created_at))
        .limit(10)
    )
    news_items = list(news_result.scalars().all())

    # 분봉 (최근 30건)
    candle_result = await db.execute(
        select(MinuteCandle)
        .where(MinuteCandle.stock_code == stock_code)
        .order_by(desc(MinuteCandle.minute_at))
        .limit(30)
    )
    candles = list(candle_result.scalars().all())

    if market_snapshot is None:
        logger.warning("시장 스냅샷 없음 stock_code=%s", stock_code)
        return None
    if not candles:
        logger.warning("분봉 데이터 없음 stock_code=%s", stock_code)
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "market": {
            "collected_at": _to_iso(market_snapshot.published_at or market_snapshot.created_at),
            "per": _safe_float(market_snapshot.per),
            "pbr": _safe_float(market_snapshot.pbr),
            "eps": _safe_float(market_snapshot.eps),
            "bps": _safe_float(market_snapshot.bps),
            "hts_avls": market_snapshot.hts_avls,
            "w52_hgpr": market_snapshot.w52_hgpr,
            "w52_lwpr": market_snapshot.w52_lwpr,
            "hts_frgn_ehrt": _safe_float(market_snapshot.hts_frgn_ehrt),
            "vol_tnrt": _safe_float(market_snapshot.vol_tnrt),
        },
        "disclosures": [
            {
                "title": d.title,
                "description": d.description,
                "published_at": _to_iso(d.published_at),
            }
            for d in disclosures
        ],
        "news": [
            {
                "title": n.title,
                "summary": n.summary,
                "useful": n.useful,
                "published_at": _to_iso(n.published_at),
            }
            for n in news_items
        ],
        "candles": [
            {
                "minute_at": _to_iso(c.minute_at),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }


async def _get_buy_reason(db: AsyncSession, stock_code: str) -> str | None:
    """가장 최근 매수 주문의 분석 이유를 반환한다."""
    result = await db.execute(
        select(OrderHistory)
        .where(OrderHistory.stock_code == stock_code)
        .where(OrderHistory.order_type == "BUY")
        .order_by(desc(OrderHistory.created_at))
        .limit(1)
    )
    buy_order = result.scalar_one_or_none()
    if buy_order is None:
        return None

    # decision_history의 parsed_decision에서 reason 추출
    dh_result = await db.execute(
        select(DecisionHistory).where(DecisionHistory.id == buy_order.decision_history_id)
    )
    dh = dh_result.scalar_one_or_none()
    if dh is None:
        return None

    parsed = dh.parsed_decision
    analysis = parsed.get("analysis") if isinstance(parsed, dict) else None
    if not analysis:
        return None
    for item in analysis:
        if item.get("stock_code") == stock_code and item.get("reason"):
            return item["reason"]
    return None


def _extract_result(parsed_decision: dict) -> str:
    decision = parsed_decision.get("decision")
    raw_result = decision.get("result") if isinstance(decision, dict) else None
    return str(raw_result).strip().upper()


def _validate_positive_order(price: Decimal, quantity: int) -> None:
    if price <= 0 or quantity <= 0:
        raise ValueError("가격과 수량은 0보다 큰 양수여야 합니다")


def _has_invalid_result(payload: dict) -> bool:
    decision = payload.get("decision")
    raw_result = decision.get("result") if isinstance(decision, dict) else None
    if raw_result is None:
        return True
    return str(raw_result).strip().upper() not in DECISION_ALLOWED_RESULTS


def _downgraded_to_hold(original_payload: dict, normalized_payload: dict) -> bool:
    original_decision = original_payload.get("decision")
    original_result = (
        str(original_decision.get("result")).strip().upper()
        if isinstance(original_decision, dict) and original_decision.get("result") is not None
        else ""
    )
    normalized_decision = normalized_payload.get("decision", {})
    normalized_result = str(normalized_decision.get("result")).strip().upper()
    return original_result in {"BUY", "SELL"} and normalized_result == "HOLD"


async def _get_recent_trades(db: AsyncSession, now: datetime) -> list[dict]:
    """최근 N분 내 체결된 주문 이력을 반환한다 (왕복매매 방지용)."""
    cutoff = now - timedelta(minutes=RECENT_TRADE_LOOKBACK_MINUTES)
    result = await db.execute(
        select(OrderHistory)
        .where(OrderHistory.created_at >= cutoff)
        .order_by(desc(OrderHistory.created_at))
    )
    orders = result.scalars().all()

    trades = []
    for order in orders:
        # decision_history에서 reason 추출
        reason = None
        dh_result = await db.execute(
            select(DecisionHistory).where(DecisionHistory.id == order.decision_history_id)
        )
        dh = dh_result.scalar_one_or_none()
        if dh and isinstance(dh.parsed_decision, dict):
            analysis = dh.parsed_decision.get("analysis")
            if analysis:
                for item in analysis:
                    if item.get("stock_code") == order.stock_code and item.get("reason"):
                        reason = item["reason"]
                        break

        trades.append({
            "side": order.order_type,
            "stock_code": order.stock_code,
            "stock_name": order.stock_name,
            "price": float(order.order_price),
            "quantity": order.order_quantity,
            "executed_at": _to_iso(order.created_at),
            "reason": reason,
        })
    return trades


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _safe_float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return _to_iso(value) or ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
