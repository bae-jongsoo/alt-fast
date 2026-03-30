"""서킷브레이커 테스트."""

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
from app.services.circuit_breaker import (
    CircuitBreakerStatus,
    check_circuit_breaker,
    reset_circuit_breaker,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(
    db: AsyncSession,
    name: str = "cb_test",
    initial_capital: Decimal = Decimal("10000000"),
) -> Strategy:
    strategy = Strategy(
        name=f"{name}_{_now().timestamp()}",
        description="서킷브레이커 테스트",
        initial_capital=initial_capital,
        is_active=True,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_decision(db: AsyncSession, strategy_id: int, decision: str = "SELL") -> DecisionHistory:
    dh = DecisionHistory(
        strategy_id=strategy_id,
        stock_code="005930",
        stock_name="삼성전자",
        decision=decision,
        request_payload="test",
        response_payload='{"decision": "' + decision + '"}',
        parsed_decision={"decision": {"result": decision}},
        processing_time_ms=100,
        is_error=False,
    )
    db.add(dh)
    await db.flush()
    return dh


async def _create_sell_order(
    db: AsyncSession,
    strategy_id: int,
    profit_loss: float,
    profit_loss_net: float | None = None,
    created_at: datetime | None = None,
) -> OrderHistory:
    """SELL 주문 생성 (profit_loss 지정)."""
    dh = await _create_decision(db, strategy_id, "SELL")
    if profit_loss_net is None:
        profit_loss_net = profit_loss

    order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=dh.id,
        stock_code="005930",
        stock_name="삼성전자",
        order_type="SELL",
        order_price=50000.0,
        order_quantity=10,
        order_total_amount=500000.0,
        result_price=50000.0,
        result_quantity=10,
        result_total_amount=500000.0,
        profit_loss=profit_loss,
        profit_rate=-1.0 if profit_loss < 0 else 1.0,
        profit_loss_net=profit_loss_net,
        profit_rate_net=-1.0 if profit_loss_net < 0 else 1.0,
    )
    if created_at is not None:
        order.order_placed_at = created_at
    db.add(order)
    await db.flush()

    if created_at is not None:
        # server_default 으로 설정된 created_at 을 수동 업데이트
        order.created_at = created_at
        await db.flush()

    await db.commit()
    await db.refresh(order)
    return order


async def _create_buy_order(
    db: AsyncSession,
    strategy_id: int,
    created_at: datetime | None = None,
) -> OrderHistory:
    """BUY 주문 생성."""
    dh = await _create_decision(db, strategy_id, "BUY")

    order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=dh.id,
        stock_code="005930",
        stock_name="삼성전자",
        order_type="BUY",
        order_price=50000.0,
        order_quantity=10,
        order_total_amount=500000.0,
        result_price=50000.0,
        result_quantity=10,
        result_total_amount=500000.0,
    )
    if created_at is not None:
        order.order_placed_at = created_at
    db.add(order)
    await db.flush()

    if created_at is not None:
        order.created_at = created_at
        await db.flush()

    await db.commit()
    await db.refresh(order)
    return order


# ─── 3연패 감지 테스트 ───


async def test_consecutive_losses_triggers_circuit_breaker(db: AsyncSession):
    """3회 연속 손실 → is_active=True."""
    strategy = await _create_strategy(db, "cb_consec")

    # 3연속 손실 주문 생성
    for i in range(3):
        await _create_sell_order(db, strategy.id, profit_loss=-10000.0 * (i + 1))

    status = await check_circuit_breaker(db, strategy.id)

    assert status.is_active is True
    assert status.consecutive_losses >= 3
    assert "연속" in status.reason


# ─── 일일 손실 한도 테스트 ───


async def test_daily_loss_limit_triggers_circuit_breaker(db: AsyncSession):
    """당일 실현 손실 합계 >= 총 자산의 3% → is_active=True."""
    # initial_capital = 10,000,000 → 3% = 300,000
    strategy = await _create_strategy(db, "cb_daily_loss")

    now = _now()
    # 당일 손실 -350,000원 (3.5% > 3%)
    await _create_sell_order(
        db,
        strategy.id,
        profit_loss=-350000.0,
        profit_loss_net=-350000.0,
        created_at=now,
    )

    status = await check_circuit_breaker(db, strategy.id)

    assert status.is_active is True
    assert status.daily_loss < 0
    assert "일일 손실" in status.reason


# ─── 일일 매매 상한 테스트 ───


async def test_daily_trade_limit_triggers_circuit_breaker(db: AsyncSession):
    """당일 매수 체결 건수 >= 5건 → is_active=True."""
    strategy = await _create_strategy(db, "cb_trade_limit")

    now = _now()
    # 5건 BUY 생성
    for _ in range(5):
        await _create_buy_order(db, strategy.id, created_at=now)

    status = await check_circuit_breaker(db, strategy.id)

    assert status.is_active is True
    assert status.remaining_trades == 0
    assert "일일 매매" in status.reason


# ─── 정상 상태 테스트 ───


async def test_normal_state_no_circuit_breaker(db: AsyncSession):
    """모든 조건 미충족 → is_active=False."""
    strategy = await _create_strategy(db, "cb_normal")

    # 수익 있는 매도 1건만
    await _create_sell_order(db, strategy.id, profit_loss=50000.0, profit_loss_net=50000.0, created_at=_now())
    # 매수 1건만
    await _create_buy_order(db, strategy.id, created_at=_now())

    status = await check_circuit_breaker(db, strategy.id)

    assert status.is_active is False
    assert status.reason is None
    assert status.remaining_trades > 0
    assert status.consecutive_losses == 0


# ─── 수동 리셋 테스트 ───


@patch("app.services.ws_collector.get_redis", new_callable=AsyncMock)
async def test_manual_reset(mock_get_redis_fn, db: AsyncSession):
    """수동 리셋 시 Redis 캐시가 삭제되고 현재 상태가 반환된다."""
    mock_redis = AsyncMock()
    mock_get_redis_fn.return_value = mock_redis

    strategy = await _create_strategy(db, "cb_reset")

    status = await reset_circuit_breaker(db, strategy.id)

    # Redis delete 호출 확인
    mock_redis.delete.assert_called_once_with(f"circuit_breaker:{strategy.id}")
    # 주문이 없으므로 정상 상태
    assert status.is_active is False


# ─── 연속 손실 카운트 정확성 (중간에 수익 있으면 리셋) ───


async def test_consecutive_losses_reset_on_profit(db: AsyncSession):
    """중간에 수익 매매가 있으면 연속 손실 카운트가 리셋된다."""
    strategy = await _create_strategy(db, "cb_reset_count")

    base_time = _now()

    # 2연속 손실 → 수익 → 1손실 (시간순)
    await _create_sell_order(
        db, strategy.id, profit_loss=-10000.0,
        created_at=base_time - timedelta(minutes=40),
    )
    await _create_sell_order(
        db, strategy.id, profit_loss=-20000.0,
        created_at=base_time - timedelta(minutes=30),
    )
    # 수익 매매 (리셋 포인트)
    await _create_sell_order(
        db, strategy.id, profit_loss=50000.0,
        created_at=base_time - timedelta(minutes=20),
    )
    # 이후 1건 손실 → 연속 1회
    await _create_sell_order(
        db, strategy.id, profit_loss=-5000.0,
        created_at=base_time - timedelta(minutes=10),
    )

    status = await check_circuit_breaker(db, strategy.id)

    assert status.consecutive_losses == 1
    assert status.is_active is False  # 1회 < 3회 한도
