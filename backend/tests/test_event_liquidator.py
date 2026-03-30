"""이벤트 기반 청산 로직 테스트."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.strategy import Strategy
from app.models.system_parameter import SystemParameter
from app.models.trading_event import TradingEvent
from app.services.event_liquidator import (
    LiquidationSignal,
    check_llm_liquidation,
    check_mechanical_liquidation,
    execute_event_sell,
    run_liquidation_check,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession, name: str = "liq_test") -> Strategy:
    strategy = Strategy(
        name=f"{name}_{_now().timestamp()}",
        description="청산 테스트",
        initial_capital=Decimal("10000000"),
        is_active=True,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_position_and_buy_order(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    buy_price: Decimal = Decimal("50000"),
    quantity: int = 10,
    target_return_pct: float | None = 5.0,
    stop_pct: float | None = -3.0,
    holding_days: int | None = 5,
    bought_days_ago: int = 0,
    event_id: int | None = None,
) -> tuple[Asset, OrderHistory]:
    """포지션과 매수 주문 생성."""
    # 현금 자산
    cash = Asset(
        strategy_id=strategy_id,
        stock_code=None,
        stock_name=None,
        quantity=1,
        unit_price=Decimal("5000000"),
        total_amount=Decimal("5000000"),
    )
    db.add(cash)

    # 포지션
    position = Asset(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name=stock_name,
        quantity=quantity,
        unit_price=float(buy_price),
        total_amount=float(buy_price * quantity),
    )
    db.add(position)

    # DecisionHistory for the buy
    buy_decision = DecisionHistory(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name=stock_name,
        decision="BUY",
        request_payload="test prompt",
        response_payload='{"decision": "BUY"}',
        parsed_decision={"decision": {"result": "BUY"}, "reasoning": "강한 매수 신호"},
        processing_time_ms=100,
        is_error=False,
    )
    db.add(buy_decision)
    await db.flush()

    buy_date = datetime.now() - timedelta(days=bought_days_ago)

    # 매수 주문
    buy_order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=buy_decision.id,
        stock_code=stock_code,
        stock_name=stock_name,
        order_type="BUY",
        order_price=float(buy_price),
        order_quantity=quantity,
        order_total_amount=float(buy_price * quantity),
        result_price=float(buy_price),
        result_quantity=quantity,
        result_total_amount=float(buy_price * quantity),
        target_return_pct=target_return_pct,
        stop_pct=stop_pct,
        holding_days=holding_days,
        event_id=event_id,
        order_placed_at=buy_date,
        result_executed_at=buy_date,
    )
    db.add(buy_order)
    await db.commit()
    await db.refresh(position)
    await db.refresh(buy_order)

    return position, buy_order


# ─── 강제 손절 테스트 ───


async def test_mechanical_stop_loss_triggered(db: AsyncSession):
    """현재가가 -2% 이하로 하락하면 기계적 손절 신호가 발생한다."""
    strategy = await _create_strategy(db, "stop_loss")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        stop_pct=-3.0,  # LLM -3%는 -2%보다 느슨 -> -2% 적용
    )

    # -2% = 49000원. 48900이면 트리거
    current_price = Decimal("48900")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "mechanical_stop"
    assert "손절" in signal.reason


async def test_mechanical_stop_loss_llm_tighter(db: AsyncSession):
    """LLM의 stop_pct이 -2%보다 타이트하면(-1%) LLM 값을 사용한다."""
    strategy = await _create_strategy(db, "stop_tight")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        stop_pct=-1.0,  # LLM -1%는 -2%보다 타이트 -> -1% 적용
    )

    # -1% = 49500원. 49400이면 트리거
    current_price = Decimal("49400")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "mechanical_stop"


async def test_mechanical_stop_loss_no_stop_pct(db: AsyncSession):
    """stop_pct이 None이면 시스템 기본값 -2% 적용."""
    strategy = await _create_strategy(db, "stop_none")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        stop_pct=None,
    )

    # -2% = 49000원. 48900이면 트리거
    current_price = Decimal("48900")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "mechanical_stop"


# ─── 목표가 도달 테스트 ───


async def test_mechanical_target_reached(db: AsyncSession):
    """현재가가 target_return_pct에 도달하면 청산 신호가 발생한다."""
    strategy = await _create_strategy(db, "target")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        target_return_pct=5.0,
    )

    # +5% = 52500원. 52600이면 트리거
    current_price = Decimal("52600")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "mechanical_target"
    assert "목표가" in signal.reason


async def test_mechanical_target_not_reached(db: AsyncSession):
    """현재가가 목표에 미달하면 청산 신호 없음."""
    strategy = await _create_strategy(db, "target_no")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        target_return_pct=5.0,
    )

    current_price = Decimal("52000")  # 4% < 5%

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is None


async def test_mechanical_target_none_skipped(db: AsyncSession):
    """target_return_pct이 None이면 목표가 청산 비활성화."""
    strategy = await _create_strategy(db, "target_none")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        target_return_pct=None,
        stop_pct=-3.0,
    )

    current_price = Decimal("60000")  # 큰 이득이어도 목표 청산 없음

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is None


# ─── 보유기간 초과 테스트 ───


async def test_mechanical_expiry_triggered(db: AsyncSession):
    """보유기간이 holding_days * 1.5 초과하면 강제 청산 신호."""
    strategy = await _create_strategy(db, "expiry")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=4,
        bought_days_ago=7,  # 7일 > 4 * 1.5 = 6일
    )

    current_price = Decimal("50000")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "mechanical_expiry"
    assert "보유기간" in signal.reason


async def test_mechanical_expiry_holding_days_none(db: AsyncSession):
    """holding_days가 None이면 보유기간 청산 비활성화."""
    strategy = await _create_strategy(db, "expiry_none")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=None,
        bought_days_ago=100,
    )

    current_price = Decimal("50000")

    signal = await check_mechanical_liquidation(
        db, strategy.id, position, buy_order, current_price
    )

    assert signal is None


# ─── LLM 판단 호출 테스트 ───


async def test_llm_liquidation_called_when_holding_days_reached(db: AsyncSession):
    """보유기간 >= holding_days 도달 시 LLM에 청산 판단 요청."""
    strategy = await _create_strategy(db, "llm_call")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=3,
        bought_days_ago=4,  # 4일 >= 3일 -> LLM 호출
        target_return_pct=10.0,
        stop_pct=-3.0,
    )

    current_price = Decimal("51000")

    mock_llm_response = '{"decision": "SELL", "reasoning": "목표 기간 경과, 추가 상승 제한적"}'

    with patch(
        "app.services.event_liquidator.ask_llm_by_level",
        new_callable=AsyncMock,
        return_value=mock_llm_response,
    ), patch(
        "app.services.event_liquidator.get_llm_level",
        new_callable=AsyncMock,
        return_value="high",
    ):
        signal = await check_llm_liquidation(
            db, strategy.id, position, buy_order, None, current_price
        )

    assert signal is not None
    assert signal.should_liquidate is True
    assert signal.signal_type == "llm_decision"


async def test_llm_liquidation_hold_response(db: AsyncSession):
    """LLM이 HOLD로 응답하면 청산 신호 없음."""
    strategy = await _create_strategy(db, "llm_hold")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=3,
        bought_days_ago=4,
    )

    current_price = Decimal("51000")

    mock_llm_response = '{"decision": "HOLD", "reasoning": "추가 상승 여력 있음"}'

    with patch(
        "app.services.event_liquidator.ask_llm_by_level",
        new_callable=AsyncMock,
        return_value=mock_llm_response,
    ), patch(
        "app.services.event_liquidator.get_llm_level",
        new_callable=AsyncMock,
        return_value="high",
    ):
        signal = await check_llm_liquidation(
            db, strategy.id, position, buy_order, None, current_price
        )

    assert signal is None


async def test_llm_liquidation_not_called_before_holding_days(db: AsyncSession):
    """보유기간이 holding_days에 미달하면 LLM 호출하지 않음."""
    strategy = await _create_strategy(db, "llm_early")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=5,
        bought_days_ago=2,  # 2일 < 5일
    )

    current_price = Decimal("51000")

    signal = await check_llm_liquidation(
        db, strategy.id, position, buy_order, None, current_price
    )

    # LLM 호출 없이 None 반환
    assert signal is None


# ─── LLM 호출 빈도 제한 테스트 ───


async def test_llm_liquidation_rate_limited(db: AsyncSession):
    """동일 포지션에 대해 1시간 내 재호출은 차단된다."""
    strategy = await _create_strategy(db, "llm_rate")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        holding_days=3,
        bought_days_ago=4,
    )

    current_price = Decimal("51000")

    # 최근 DecisionHistory 추가 (1시간 이내)
    recent_decision = DecisionHistory(
        strategy_id=strategy.id,
        stock_code="005930",
        stock_name="삼성전자",
        decision="HOLD",
        request_payload="recent sell check prompt",
        response_payload='{"decision": "HOLD"}',
        parsed_decision={"decision": {"result": "HOLD"}},
        processing_time_ms=50,
        is_error=False,
    )
    db.add(recent_decision)
    await db.commit()

    # LLM이 호출되지 않아야 하므로 mock을 설정하지 않아도 됨
    signal = await check_llm_liquidation(
        db, strategy.id, position, buy_order, None, current_price
    )

    assert signal is None


# ─── execute_event_sell 통합 테스트 ───


async def test_execute_event_sell_creates_order_and_updates(db: AsyncSession):
    """execute_event_sell이 가상 매도 + 손익 계산 + 주문 기록을 올바르게 수행한다."""
    strategy = await _create_strategy(db, "sell_exec")
    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        quantity=10,
    )

    current_price = Decimal("52000")
    signal = LiquidationSignal(
        should_liquidate=True,
        reason="목표가 도달 테스트",
        signal_type="mechanical_target",
    )

    with patch(
        "app.services.event_liquidator.send_message",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_telegram:
        order = await execute_event_sell(
            db, strategy.id, position, buy_order, signal, current_price
        )
        await db.commit()

    # OrderHistory 검증
    assert order.order_type == "SELL"
    assert order.stock_code == "005930"
    assert order.result_price == float(current_price)
    assert order.result_quantity == 10
    assert order.buy_order_id == buy_order.id

    # 손익 계산 검증
    expected_profit = float((Decimal("52000") - Decimal("50000")) * 10)
    assert order.profit_loss == pytest.approx(expected_profit, abs=1)
    assert order.profit_rate > 0
    assert order.profit_loss_net is not None
    assert order.profit_loss_net < expected_profit  # 세후 < 세전

    # Telegram 알림 호출 확인
    mock_telegram.assert_called_once()
    msg = mock_telegram.call_args[0][0]
    assert "청산" in msg
    assert "삼성전자" in msg


async def test_execute_event_sell_with_event_updates_status(db: AsyncSession):
    """이벤트가 연결된 청산 시 TradingEvent 상태가 closed로 업데이트된다."""
    strategy = await _create_strategy(db, "sell_event")

    # TradingEvent 생성
    event = TradingEvent(
        event_type="volume_spike",
        stock_code="005930",
        stock_name="삼성전자",
        event_data={"spike_ratio": 3.0},
        confidence_hint=Decimal("0.70"),
        status="decided",
        strategy_id=strategy.id,
        detected_at=_now(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    position, buy_order = await _create_position_and_buy_order(
        db, strategy.id,
        buy_price=Decimal("50000"),
        quantity=10,
        event_id=event.id,
    )

    current_price = Decimal("48000")
    signal = LiquidationSignal(
        should_liquidate=True,
        reason="강제 손절",
        signal_type="mechanical_stop",
    )

    with patch(
        "app.services.event_liquidator.send_message",
        new_callable=AsyncMock,
        return_value=True,
    ):
        order = await execute_event_sell(
            db, strategy.id, position, buy_order, signal, current_price
        )
        await db.commit()

    # 이벤트 상태 확인
    await db.refresh(event)
    assert event.status == "closed"
    assert event.processed_at is not None

    # 주문에 event_id 연결 확인
    assert order.event_id == event.id

    # 손실 확인
    assert order.profit_loss < 0
