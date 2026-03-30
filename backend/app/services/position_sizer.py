"""포지션 사이징 + 이벤트 기반 매수 실행."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.trading_event import TradingEvent
from app.services.asset_manager import (
    apply_virtual_buy,
    get_cash_asset,
    get_open_position,
)
from app.services.param_helper import get_param

logger = logging.getLogger(__name__)

# ── 기본 상수 ────────────────────────────────────────────────────
DEFAULT_FIXED_AMOUNT = Decimal("500000")       # 50만원
DEFAULT_MAX_SINGLE_STOCK_PCT = Decimal("0.20")  # 총 자산의 20%
DEFAULT_MIN_CASH_RESERVE_PCT = Decimal("0.10")  # 총 자산의 10% 현금 유지
MAX_KELLY_FRACTION = 0.1                        # Half-Kelly 최대 캡 10%
MIN_KELLY_TRADES = 50                           # Kelly 모드 최소 매매 이력


@dataclass
class SizingResult:
    quantity: int = 0
    total_amount: Decimal = Decimal("0")
    sizing_method: str = "fixed"
    kelly_fraction: float | None = None
    details: dict = field(default_factory=dict)


# ── Kelly 통계 계산 ───────────────────────────────────────────────

async def _compute_kelly_stats(
    db: AsyncSession, strategy_id: int
) -> tuple[int, float, float, float] | None:
    """전략의 과거 SELL 주문에서 win_rate, avg_win, avg_loss 계산.

    Returns (count, win_rate, avg_win, avg_loss) 또는 데이터 부족 시 None.
    """
    result = await db.execute(
        select(OrderHistory.profit_rate_net).where(
            OrderHistory.strategy_id == strategy_id,
            OrderHistory.order_type == "SELL",
            OrderHistory.profit_rate_net.isnot(None),
        )
    )
    profit_rates = [row for (row,) in result.all()]

    if len(profit_rates) < MIN_KELLY_TRADES:
        return None

    wins = [r for r in profit_rates if r > 0]
    losses = [r for r in profit_rates if r <= 0]

    win_rate = len(wins) / len(profit_rates) if profit_rates else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0

    return len(profit_rates), win_rate, avg_win, avg_loss


# ── 메인: 포지션 사이징 ──────────────────────────────────────────

async def calculate_position_size(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str,
    current_price: Decimal,
    confidence: float,
    target_return_pct: float | None = None,
    stop_pct: float | None = None,
) -> SizingResult:
    """매수 수량을 결정한다."""
    sizing_mode = await get_param(db, "event_trader_sizing_mode", "fixed", strategy_id=strategy_id)
    fixed_amount_str = await get_param(db, "event_trader_fixed_amount", "500000", strategy_id=strategy_id)
    max_single_pct = Decimal(
        await get_param(db, "event_trader_max_single_stock_pct", "0.20", strategy_id=strategy_id)
    )
    min_cash_reserve_pct = Decimal(
        await get_param(db, "event_trader_min_cash_reserve_pct", "0.10", strategy_id=strategy_id)
    )

    cash_asset = await get_cash_asset(db, strategy_id)
    cash = Decimal(str(cash_asset.total_amount))

    # 총 자산 = 현금 + 보유 종목 평가액
    position = await get_open_position(db, strategy_id)
    stock_value = Decimal("0")
    if position is not None:
        stock_value = Decimal(str(position.total_amount))
    total_capital = cash + stock_value

    details: dict = {
        "cash": str(cash),
        "total_capital": str(total_capital),
        "sizing_mode": sizing_mode,
    }

    # ── 투자 가능 금액 한도 계산 ────────────────────────────
    # 1) 단일 종목 최대 투자 비중
    max_by_single = total_capital * max_single_pct
    # 2) 최소 잔여 현금 확보
    min_cash = total_capital * min_cash_reserve_pct
    available_cash = max(cash - min_cash, Decimal("0"))
    # 3) 투자 가능 금액
    max_investable = min(max_by_single, available_cash)

    details["max_by_single_stock"] = str(max_by_single)
    details["min_cash_reserve"] = str(min_cash)
    details["available_cash"] = str(available_cash)
    details["max_investable"] = str(max_investable)

    if max_investable <= 0:
        return SizingResult(
            quantity=0,
            total_amount=Decimal("0"),
            sizing_method=sizing_mode,
            details={**details, "reason": "투자 가능 금액 없음"},
        )

    # ── 사이징 모드별 목표 금액 ──────────────────────────────
    kelly_fraction: float | None = None

    if sizing_mode == "kelly":
        stats = await _compute_kelly_stats(db, strategy_id)
        if stats is not None:
            count, win_rate, avg_win, avg_loss = stats
            details["kelly_stats"] = {
                "trade_count": count,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
            }
            # Kelly% = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            if avg_win > 0:
                raw_kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            else:
                raw_kelly = 0.0
            # Half-Kelly
            half_kelly = raw_kelly / 2
            # confidence 반영
            fraction = half_kelly * confidence
            # 캡 적용
            fraction = min(fraction, MAX_KELLY_FRACTION)
            fraction = max(fraction, 0.0)
            kelly_fraction = fraction

            target_amount = total_capital * Decimal(str(fraction))
            details["raw_kelly"] = raw_kelly
            details["half_kelly"] = half_kelly
            details["final_fraction"] = fraction
        else:
            # 데이터 부족 → fixed 모드 폴백
            details["kelly_fallback"] = "insufficient_data"
            target_amount = Decimal(fixed_amount_str)
    else:
        target_amount = Decimal(fixed_amount_str)

    details["target_amount_before_cap"] = str(target_amount)

    # ── 한도 적용 ─────────────────────────────────────────
    invest_amount = min(target_amount, max_investable)
    if invest_amount <= 0:
        return SizingResult(
            quantity=0,
            total_amount=Decimal("0"),
            sizing_method=sizing_mode,
            kelly_fraction=kelly_fraction,
            details={**details, "reason": "투자 금액 ≤ 0"},
        )

    quantity = int(invest_amount // current_price)
    if quantity <= 0:
        return SizingResult(
            quantity=0,
            total_amount=Decimal("0"),
            sizing_method=sizing_mode,
            kelly_fraction=kelly_fraction,
            details={**details, "reason": "수량 0 (주가 대비 금액 부족)"},
        )

    actual_amount = current_price * quantity
    return SizingResult(
        quantity=quantity,
        total_amount=actual_amount,
        sizing_method=sizing_mode,
        kelly_fraction=kelly_fraction,
        details=details,
    )


# ── 매수 실행 ────────────────────────────────────────────────────

async def execute_event_buy(
    db: AsyncSession,
    strategy_id: int,
    event: TradingEvent,
    decision: "EventDecisionResponse",  # noqa: F821
    decision_history: DecisionHistory,
) -> OrderHistory | None:
    """이벤트 기반 매수 실행.

    1. calculate_position_size()
    2. 수량 0 → None 반환 (매수 포기)
    3. apply_virtual_buy() (기존 asset_manager 활용)
    4. OrderHistory 생성 (decision_history_id, event_id 연결)
    5. TradingEvent에 결과 기록
    """
    from app.schemas.event_decision import EventDecisionResponse  # noqa: F811

    current_price = Decimal(str(decision.target_return_pct or 0))
    # current_price는 시장가(event_data에서 가져옴)
    price_raw = (event.event_data or {}).get("current_price")
    if price_raw is None:
        logger.warning("이벤트에 current_price 없음, 매수 포기: event_id=%s", event.id)
        return None
    current_price = Decimal(str(price_raw))

    sizing = await calculate_position_size(
        db=db,
        strategy_id=strategy_id,
        stock_code=event.stock_code,
        current_price=current_price,
        confidence=decision.confidence,
        target_return_pct=decision.target_return_pct,
        stop_pct=decision.stop_pct,
    )

    if sizing.quantity == 0:
        logger.info(
            "매수 포기 (수량 0): stock=%s details=%s",
            event.stock_code, sizing.details,
        )
        event.status = "skipped"
        event.processed_at = datetime.now()
        await db.flush()
        return None

    # 가상 매수 실행
    await apply_virtual_buy(
        db=db,
        strategy_id=strategy_id,
        stock_code=event.stock_code,
        stock_name=event.stock_name,
        price=current_price,
        quantity=sizing.quantity,
    )

    # OrderHistory 생성
    order_total = current_price * sizing.quantity
    executed_at = datetime.now()
    order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=decision_history.id,
        stock_code=event.stock_code,
        stock_name=event.stock_name,
        order_type="BUY",
        order_price=float(current_price),
        order_quantity=sizing.quantity,
        order_total_amount=float(order_total),
        result_price=float(current_price),
        result_quantity=sizing.quantity,
        result_total_amount=float(order_total),
        event_id=event.id,
        target_return_pct=decision.target_return_pct,
        stop_pct=decision.stop_pct,
        holding_days=decision.holding_days,
        order_placed_at=executed_at,
        result_executed_at=executed_at,
    )
    db.add(order)

    # TradingEvent 상태 업데이트
    event.status = "executed"
    event.processed_at = executed_at
    await db.flush()

    logger.info(
        "이벤트 매수 실행: order_id=%s stock=%s price=%s qty=%s method=%s",
        order.id, event.stock_code, current_price, sizing.quantity, sizing.sizing_method,
    )
    return order
