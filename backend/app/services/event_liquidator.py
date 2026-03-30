"""이벤트 기반 청산 로직.

LLM이 매수 시 제시한 목표가/손절가/보유기간을 기반으로 보유 포지션을 청산한다.
기계적 안전장치(-2% 강제 손절)를 포함한다.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jinja2 import BaseLoader, Environment
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.models.trading_event import TradingEvent
from app.services.param_helper import get_param
from app.services.asset_manager import (
    COMMISSION_RATE,
    TRANSACTION_TAX_RATE,
    apply_virtual_sell,
    get_open_position,
)
from app.shared.llm import ask_llm_by_level, get_llm_level
from app.shared.telegram import send_message

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DEFAULT_STOP_PCT = Decimal("-2")  # 기본 강제 손절 -2%

_jinja_env = Environment(loader=BaseLoader(), keep_trailing_newline=True)


@dataclass
class LiquidationSignal:
    should_liquidate: bool
    reason: str
    signal_type: str  # "mechanical_stop", "mechanical_target", "mechanical_expiry", "llm_decision"


# ---------------------------------------------------------------------------
# 기계적 청산 체크
# ---------------------------------------------------------------------------


async def _get_system_default_stop_pct(db: AsyncSession, strategy_id: int | None = None) -> Decimal:
    """시스템 파라미터에서 기본 손절 비율을 읽는다."""
    val = await get_param(db, "event_trader_default_stop_pct", str(DEFAULT_STOP_PCT), strategy_id=strategy_id)
    try:
        return Decimal(val)
    except Exception:
        return DEFAULT_STOP_PCT


async def check_mechanical_liquidation(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    current_price: Decimal,
) -> LiquidationSignal | None:
    """기계적 청산 조건 체크. 하나라도 만족하면 즉시 청산 신호 반환."""
    avg_buy_price = Decimal(str(buy_order.result_price))
    system_stop_pct = await _get_system_default_stop_pct(db)

    # 1. 강제 손절 체크
    order_stop_pct = Decimal(str(buy_order.stop_pct)) if buy_order.stop_pct is not None else None

    # LLM stop_pct과 시스템 -2% 중 더 타이트한(큰) 값 사용
    # stop_pct은 음수 (예: -2.0), 더 타이트 = 값이 더 큰 쪽 (예: -1.5 > -2.0)
    if order_stop_pct is not None:
        effective_stop_pct = max(order_stop_pct, system_stop_pct)
    else:
        effective_stop_pct = system_stop_pct

    stop_price = avg_buy_price * (1 + effective_stop_pct / 100)
    if current_price <= stop_price:
        pct = float((current_price - avg_buy_price) / avg_buy_price * 100)
        return LiquidationSignal(
            should_liquidate=True,
            reason=f"손절 도달: 현재가 {current_price} <= 손절가 {stop_price:.0f} (매수가 {avg_buy_price}, 손절 {effective_stop_pct}%, 수익률 {pct:.2f}%)",
            signal_type="mechanical_stop",
        )

    # 2. 목표가 도달 체크
    if buy_order.target_return_pct is not None:
        target_pct = Decimal(str(buy_order.target_return_pct))
        target_price = avg_buy_price * (1 + target_pct / 100)
        if current_price >= target_price:
            pct = float((current_price - avg_buy_price) / avg_buy_price * 100)
            return LiquidationSignal(
                should_liquidate=True,
                reason=f"목표가 도달: 현재가 {current_price} >= 목표가 {target_price:.0f} (매수가 {avg_buy_price}, 목표 {target_pct}%, 수익률 {pct:.2f}%)",
                signal_type="mechanical_target",
            )

    # 3. 보유기간 초과 체크
    if buy_order.holding_days is not None:
        buy_date = buy_order.result_executed_at or buy_order.order_placed_at
        days_held = (datetime.now() - buy_date).days
        max_days = int(buy_order.holding_days * 1.5)
        if days_held > max_days:
            return LiquidationSignal(
                should_liquidate=True,
                reason=f"보유기간 초과: {days_held}일 보유 > 최대 {max_days}일 (예상 {buy_order.holding_days}일 * 1.5)",
                signal_type="mechanical_expiry",
            )

    return None


# ---------------------------------------------------------------------------
# LLM 기반 청산 판단
# ---------------------------------------------------------------------------


async def _has_recent_liquidation_check(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str,
    hours: int = 1,
) -> bool:
    """동일 포지션에 대해 최근 N시간 내 청산 판단(SELL decision)이 있었는지 체크."""
    cutoff = datetime.now() - timedelta(hours=hours)
    result = await db.execute(
        select(DecisionHistory)
        .where(
            DecisionHistory.strategy_id == strategy_id,
            DecisionHistory.stock_code == stock_code,
            DecisionHistory.decision.in_(["SELL", "HOLD"]),
            DecisionHistory.created_at >= cutoff,
            DecisionHistory.request_payload.isnot(None),
        )
        .order_by(desc(DecisionHistory.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def check_llm_liquidation(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    event: TradingEvent | None,
    current_price: Decimal,
) -> LiquidationSignal | None:
    """LLM에게 청산 판단을 요청한다. 보유기간 >= holding_days 도달 시에만 호출."""
    # 보유기간 도달 확인
    if buy_order.holding_days is None:
        return None

    buy_date = buy_order.result_executed_at or buy_order.order_placed_at
    days_held = (datetime.now() - buy_date).days
    if days_held < buy_order.holding_days:
        return None

    # 빈도 제한: 1시간 1회
    stock_code = position.stock_code
    if await _has_recent_liquidation_check(db, strategy_id, stock_code, hours=1):
        return None

    # 프롬프트 빌드
    template = await _get_prompt_template(db, strategy_id, "event_sell")
    avg_buy_price = Decimal(str(buy_order.result_price))
    profit_rate = float((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0.0

    context = {
        "stock_code": stock_code,
        "stock_name": position.stock_name or "",
        "avg_buy_price": float(avg_buy_price),
        "current_price": float(current_price),
        "profit_rate": round(profit_rate, 2),
        "days_held": days_held,
        "holding_days": buy_order.holding_days,
        "target_return_pct": float(buy_order.target_return_pct) if buy_order.target_return_pct else None,
        "stop_pct": float(buy_order.stop_pct) if buy_order.stop_pct else None,
        "buy_reasoning": "",
        "event_type": event.event_type if event else None,
        "event_data": event.event_data if event else None,
    }

    # 매수 DecisionHistory에서 reasoning 추출
    buy_decision_result = await db.execute(
        select(DecisionHistory)
        .where(DecisionHistory.id == buy_order.decision_history_id)
    )
    buy_decision = buy_decision_result.scalar_one_or_none()
    if buy_decision and buy_decision.parsed_decision:
        context["buy_reasoning"] = buy_decision.parsed_decision.get("reasoning", "")

    if template:
        context_json = json.dumps(context, ensure_ascii=False, default=str, indent=2)
        prompt = _jinja_env.from_string(template.content).render(
            current_time=datetime.now().isoformat(),
            stock_code=stock_code,
            stock_name=position.stock_name or "",
            context_json=context_json,
        )
    else:
        prompt = _build_default_sell_prompt(context)

    # LLM 호출
    started_at = time.monotonic()
    is_error = False
    error_message: str | None = None
    response_payload = ""
    decision_str = "HOLD"

    try:
        level = await get_llm_level("llm_event_trading", "high")
        response_payload = await ask_llm_by_level(level, prompt)
        decision_str = _parse_sell_decision(response_payload)
    except Exception as exc:
        is_error = True
        error_message = str(exc)
        decision_str = "HOLD"

    # DecisionHistory 기록
    processing_time_ms = int((time.monotonic() - started_at) * 1000)
    history = DecisionHistory(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name=position.stock_name or "",
        decision=decision_str,
        request_payload=prompt,
        response_payload=response_payload,
        parsed_decision={"decision": {"result": decision_str}},
        processing_time_ms=max(processing_time_ms, 0),
        is_error=is_error,
        error_message=error_message,
    )
    db.add(history)
    await db.flush()

    if decision_str == "SELL":
        return LiquidationSignal(
            should_liquidate=True,
            reason=f"LLM 청산 판단: {days_held}일 보유, 수익률 {profit_rate:.2f}%",
            signal_type="llm_decision",
        )

    return None


def _parse_sell_decision(raw_response: str) -> str:
    """LLM 응답에서 SELL/HOLD 판단을 파싱."""
    from app.shared.json_helpers import parse_llm_json_object

    try:
        payload = parse_llm_json_object(raw_response)
        raw_decision = payload.get("decision", "HOLD")
        if isinstance(raw_decision, dict):
            raw_decision = raw_decision.get("result", "HOLD")
        decision = str(raw_decision).strip().upper()
        if decision in ("SELL", "HOLD"):
            return decision
    except Exception:
        pass
    return "HOLD"


def _build_default_sell_prompt(context: dict) -> str:
    """프롬프트 템플릿이 없을 때 기본 프롬프트 생성."""
    return (
        f"당신은 이벤트 기반 트레이딩 전문가입니다.\n"
        f"다음 보유 포지션의 청산 여부를 판단하세요.\n\n"
        f"종목: {context['stock_name']} ({context['stock_code']})\n"
        f"매수가: {context['avg_buy_price']}\n"
        f"현재가: {context['current_price']}\n"
        f"수익률: {context['profit_rate']}%\n"
        f"보유일수: {context['days_held']}일 (예상: {context['holding_days']}일)\n"
        f"매수 근거: {context['buy_reasoning']}\n\n"
        f'JSON으로 응답하세요: {{"decision": "SELL" 또는 "HOLD", "reasoning": "..."}}'
    )


# ---------------------------------------------------------------------------
# 청산 실행
# ---------------------------------------------------------------------------


async def execute_event_sell(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    signal: LiquidationSignal,
    current_price: Decimal,
) -> OrderHistory:
    """
    청산 실행:
    1. apply_virtual_sell() (기존 asset_manager 활용)
    2. OrderHistory 생성 (profit_loss, profit_rate, net 계산)
    3. buy_order_id 연결
    4. TradingEvent 상태 업데이트
    5. Telegram 알림
    """
    stock_code = position.stock_code
    stock_name = position.stock_name or ""
    quantity = position.quantity
    avg_buy_price = Decimal(str(position.unit_price))
    order_total_amount = current_price * quantity

    # 손익 계산
    profit_loss = (current_price - avg_buy_price) * quantity
    profit_rate = float((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0.0

    # 세후 손익
    buy_cost = avg_buy_price * quantity
    sell_cost = current_price * quantity
    total_fee = buy_cost * COMMISSION_RATE + sell_cost * COMMISSION_RATE + sell_cost * TRANSACTION_TAX_RATE
    profit_loss_net = profit_loss - total_fee
    profit_rate_net = float(profit_loss_net / buy_cost * 100) if buy_cost > 0 else 0.0

    executed_at = datetime.now()

    # DecisionHistory 생성 (기계적 청산인 경우)
    decision_history = DecisionHistory(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name=stock_name,
        decision="SELL",
        request_payload=None,
        response_payload=None,
        parsed_decision={
            "decision": {"result": "SELL"},
            "signal_type": signal.signal_type,
            "reason": signal.reason,
        },
        processing_time_ms=0,
        is_error=False,
    )
    db.add(decision_history)
    await db.flush()

    # 가상 매도 적용
    await apply_virtual_sell(db, strategy_id, stock_code, current_price, quantity)

    # OrderHistory 생성
    order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=decision_history.id,
        buy_order_id=buy_order.id,
        event_id=buy_order.event_id,
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="SELL",
        order_price=float(current_price),
        order_quantity=quantity,
        order_total_amount=float(order_total_amount),
        result_price=float(current_price),
        result_quantity=quantity,
        result_total_amount=float(order_total_amount),
        profit_loss=float(profit_loss),
        profit_rate=profit_rate,
        profit_loss_net=float(profit_loss_net),
        profit_rate_net=profit_rate_net,
        order_placed_at=executed_at,
        result_executed_at=executed_at,
    )
    db.add(order)
    await db.flush()

    # TradingEvent 상태 업데이트
    if buy_order.event_id:
        event_result = await db.execute(
            select(TradingEvent).where(TradingEvent.id == buy_order.event_id)
        )
        event = event_result.scalar_one_or_none()
        if event:
            event.status = "closed"
            event.processed_at = executed_at
            await db.flush()

    # Telegram 알림
    emoji = "+" if profit_loss >= 0 else ""
    msg = (
        f"[청산] {stock_name}({stock_code})\n"
        f"유형: {signal.signal_type}\n"
        f"사유: {signal.reason}\n"
        f"매도가: {current_price:,}원 x {quantity}주\n"
        f"손익: {emoji}{float(profit_loss):,.0f}원 ({profit_rate:+.2f}%)\n"
        f"세후: {emoji}{float(profit_loss_net):,.0f}원 ({profit_rate_net:+.2f}%)"
    )
    await send_message(msg)

    logger.info(
        "이벤트 청산 실행: order_id=%s stock=%s signal=%s profit_loss=%s",
        order.id, stock_code, signal.signal_type, profit_loss,
    )

    return order


# ---------------------------------------------------------------------------
# 청산 체크 루프
# ---------------------------------------------------------------------------


async def run_liquidation_check(
    db: AsyncSession,
    strategy_id: int,
    current_price_map: dict[str, Decimal] | None = None,
) -> OrderHistory | None:
    """
    보유 포지션에 대해 청산 체크 실행:
    1. 기계적 청산 체크 (즉시)
    2. 해당 없으면 -> 보유기간 도달 시 LLM 청산 판단
    3. 청산 신호 발생 시 -> execute_event_sell()
    """
    position = await get_open_position(db, strategy_id)
    if position is None:
        return None

    stock_code = position.stock_code

    # 직전 BUY 주문 찾기
    buy_order_result = await db.execute(
        select(OrderHistory)
        .where(
            OrderHistory.strategy_id == strategy_id,
            OrderHistory.stock_code == stock_code,
            OrderHistory.order_type == "BUY",
        )
        .order_by(desc(OrderHistory.created_at))
        .limit(1)
    )
    buy_order = buy_order_result.scalar_one_or_none()
    if buy_order is None:
        return None

    # 현재가 조회
    current_price: Decimal | None = None
    if current_price_map and stock_code in current_price_map:
        current_price = current_price_map[stock_code]

    if current_price is None:
        return None

    # 1. 기계적 청산 체크
    signal = await check_mechanical_liquidation(
        db, strategy_id, position, buy_order, current_price
    )

    # 2. LLM 청산 판단
    if signal is None:
        # 이벤트 조회
        event: TradingEvent | None = None
        if buy_order.event_id:
            event_result = await db.execute(
                select(TradingEvent).where(TradingEvent.id == buy_order.event_id)
            )
            event = event_result.scalar_one_or_none()

        signal = await check_llm_liquidation(
            db, strategy_id, position, buy_order, event, current_price
        )

    # 3. 청산 실행
    if signal is not None and signal.should_liquidate:
        return await execute_event_sell(
            db, strategy_id, position, buy_order, signal, current_price
        )

    return None


# ---------------------------------------------------------------------------
# 내부 헬퍼
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
