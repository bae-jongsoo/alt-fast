"""포지션 사이징 + 이벤트 매수 실행 테스트."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.strategy import Strategy
from app.models.system_parameter import SystemParameter
from app.models.trading_event import TradingEvent
from app.schemas.event_decision import EventDecisionResponse
from app.services.position_sizer import (
    SizingResult,
    calculate_position_size,
    execute_event_buy,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession, capital: Decimal = Decimal("10000000")) -> Strategy:
    strategy = Strategy(
        name=f"test_sizer_{_now().timestamp()}",
        description="포지션 사이징 테스트",
        initial_capital=capital,
        is_active=True,
    )
    db.add(strategy)
    await db.flush()
    return strategy


async def _create_cash_asset(db: AsyncSession, strategy_id: int, amount: float) -> Asset:
    cash = Asset(
        strategy_id=strategy_id,
        stock_code=None,
        stock_name=None,
        quantity=1,
        unit_price=amount,
        total_amount=amount,
    )
    db.add(cash)
    await db.flush()
    return cash


async def _set_param(db: AsyncSession, key: str, value: str) -> None:
    param = SystemParameter(key=key, value=value)
    db.add(param)
    await db.flush()


# ── 8.1.1 고정 소액 모드 ──────────────────────────────────────

class TestFixedMode:
    async def test_fixed_amount_basic(self, db: AsyncSession):
        """고정 소액 모드: 50만원, 주가 10,000원 -> 50주."""
        strategy = await _create_strategy(db)
        await _create_cash_asset(db, strategy.id, 10_000_000)

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=0.8,
        )

        assert result.quantity == 50
        assert result.total_amount == Decimal("500000")
        assert result.sizing_method == "fixed"

    async def test_cash_shortage_reduces_quantity(self, db: AsyncSession):
        """현금 부족 시 수량 축소."""
        strategy = await _create_strategy(db)
        # 현금 30만원만 있음 (총 자산 30만, 최소 잔여 현금 10% = 3만)
        # 사용 가능 = 30만 - 3만 = 27만
        # 단일 종목 제한 = 30만 * 20% = 6만
        # max_investable = min(6만, 27만) = 6만
        # 주가 1만원 -> 6주
        await _create_cash_asset(db, strategy.id, 300_000)

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=0.8,
        )

        # 고정 50만원이지만 단일 종목 제한(20%) = 6만원 -> 6주
        assert result.quantity == 6
        assert result.total_amount == Decimal("60000")

    async def test_zero_quantity_when_no_cash(self, db: AsyncSession):
        """현금이 거의 없으면 매수 포기."""
        strategy = await _create_strategy(db)
        await _create_cash_asset(db, strategy.id, 1_000)  # 1,000원

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("50000"),
            confidence=0.9,
        )

        assert result.quantity == 0
        assert result.total_amount == Decimal("0")


# ── 8.1.2 Kelly 모드 ─────────────────────────────────────────

class TestKellyMode:
    async def _setup_kelly(self, db: AsyncSession, win_rate: float = 0.6):
        """Kelly 테스트용 전략 + 과거 매매 이력 생성."""
        strategy = await _create_strategy(db, capital=Decimal("10000000"))
        await _create_cash_asset(db, strategy.id, 10_000_000)
        await _set_param(db, f"event_trader_sizing_mode", "kelly")

        # 과거 SELL 주문 50건 생성 (win_rate 기반)
        num_wins = int(50 * win_rate)
        num_losses = 50 - num_wins

        # DecisionHistory 생성 (FK 참조용)
        dh = DecisionHistory(
            strategy_id=strategy.id,
            stock_code="005930",
            stock_name="삼성전자",
            decision="SELL",
            processing_time_ms=100,
        )
        db.add(dh)
        await db.flush()

        now = _now()
        for i in range(num_wins):
            order = OrderHistory(
                strategy_id=strategy.id,
                decision_history_id=dh.id,
                stock_code="005930",
                stock_name="삼성전자",
                order_type="SELL",
                order_price=10000,
                order_quantity=10,
                order_total_amount=100000,
                result_price=10000,
                result_quantity=10,
                result_total_amount=100000,
                profit_loss=5000,
                profit_rate=5.0,
                profit_loss_net=4500,
                profit_rate_net=4.5,  # +4.5%
                order_placed_at=now - timedelta(days=50 - i),
                result_executed_at=now - timedelta(days=50 - i),
            )
            db.add(order)

        for i in range(num_losses):
            order = OrderHistory(
                strategy_id=strategy.id,
                decision_history_id=dh.id,
                stock_code="005930",
                stock_name="삼성전자",
                order_type="SELL",
                order_price=10000,
                order_quantity=10,
                order_total_amount=100000,
                result_price=10000,
                result_quantity=10,
                result_total_amount=100000,
                profit_loss=-3000,
                profit_rate=-3.0,
                profit_loss_net=-3200,
                profit_rate_net=-3.2,  # -3.2%
                order_placed_at=now - timedelta(days=20 - i),
                result_executed_at=now - timedelta(days=20 - i),
            )
            db.add(order)

        await db.flush()
        return strategy

    async def test_kelly_calculation(self, db: AsyncSession):
        """Kelly 모드: win_rate=0.6, avg_win=4.5, avg_loss=3.2 기반 사이징."""
        strategy = await self._setup_kelly(db, win_rate=0.6)

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=0.8,
        )

        assert result.sizing_method == "kelly"
        assert result.kelly_fraction is not None
        assert result.kelly_fraction > 0
        assert result.quantity > 0

        # Kelly% = (0.6 * 4.5 - 0.4 * 3.2) / 4.5 = (2.7 - 1.28) / 4.5 = 0.3156
        # Half-Kelly = 0.1578
        # confidence 반영 = 0.1578 * 0.8 = 0.1262
        # 캡 적용 = min(0.1262, 0.1) = 0.1
        assert result.kelly_fraction == pytest.approx(0.1, abs=0.001)

    async def test_half_kelly_cap(self, db: AsyncSession):
        """Half-Kelly 캡 (최대 10%) 적용 확인."""
        strategy = await self._setup_kelly(db, win_rate=0.6)

        # confidence=1.0으로 캡 테스트
        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=1.0,
        )

        # Half-Kelly = 0.1578 -> 캡 0.1
        assert result.kelly_fraction is not None
        assert result.kelly_fraction <= 0.1

    async def test_kelly_fallback_insufficient_data(self, db: AsyncSession):
        """Kelly 모드지만 매매 이력 부족 시 fixed 폴백."""
        strategy = await _create_strategy(db)
        await _create_cash_asset(db, strategy.id, 10_000_000)
        await _set_param(db, "event_trader_sizing_mode", "kelly")

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=0.8,
        )

        # 데이터 부족 -> fixed 폴백 -> 50주
        assert result.quantity == 50
        assert result.kelly_fraction is None
        assert "kelly_fallback" in result.details


# ── 8.1.3 안전장치 ────────────────────────────────────────────

class TestSafetyGuards:
    async def test_max_single_stock_ratio(self, db: AsyncSession):
        """단일 종목 최대 투자 비중 (20%) 제한."""
        strategy = await _create_strategy(db)
        # 현금 100만원, 총 자산 100만원
        # 단일 종목 제한 = 100만 * 20% = 20만
        # fixed_amount = 50만 -> 20만으로 제한
        # 주가 1만원 -> 20주
        await _create_cash_asset(db, strategy.id, 1_000_000)

        result = await calculate_position_size(
            db=db,
            strategy_id=strategy.id,
            stock_code="005930",
            current_price=Decimal("10000"),
            confidence=0.8,
        )

        # max_investable = min(20만, 90만) = 20만 -> 20주
        assert result.quantity == 20
        assert result.total_amount == Decimal("200000")


# ── 8.2 매수 실행 통합 테스트 ──────────────────────────────────

class TestExecuteEventBuy:
    async def test_execute_buy_creates_order(self, db: AsyncSession):
        """execute_event_buy() 통합 테스트: 가상 매수 + OrderHistory 생성."""
        strategy = await _create_strategy(db)
        await _create_cash_asset(db, strategy.id, 10_000_000)

        # DecisionHistory 생성
        dh = DecisionHistory(
            strategy_id=strategy.id,
            stock_code="005930",
            stock_name="삼성전자",
            decision="BUY",
            processing_time_ms=200,
        )
        db.add(dh)
        await db.flush()

        # TradingEvent 생성
        event = TradingEvent(
            event_type="dart_disclosure",
            stock_code="005930",
            stock_name="삼성전자",
            event_data={"current_price": 10000},
            confidence_hint=0.8,
            status="pending",
            strategy_id=strategy.id,
            decision_history_id=dh.id,
            detected_at=_now(),
        )
        db.add(event)
        await db.flush()

        decision = EventDecisionResponse(
            decision="BUY",
            confidence=0.8,
            reasoning="테스트",
            target_return_pct=3.0,
            stop_pct=-2.0,
            holding_days=5,
        )

        order = await execute_event_buy(
            db=db,
            strategy_id=strategy.id,
            event=event,
            decision=decision,
            decision_history=dh,
        )

        assert order is not None
        assert order.order_type == "BUY"
        assert order.stock_code == "005930"
        assert order.order_quantity == 50  # 50만 / 1만 = 50주
        assert order.event_id == event.id
        assert order.target_return_pct == pytest.approx(3.0)
        assert order.stop_pct == pytest.approx(-2.0)
        assert order.holding_days == 5
        assert event.status == "executed"

    async def test_execute_buy_skips_on_zero_quantity(self, db: AsyncSession):
        """수량 0이면 매수 포기 + 이벤트 skipped 상태."""
        strategy = await _create_strategy(db)
        await _create_cash_asset(db, strategy.id, 500)  # 현금 500원

        dh = DecisionHistory(
            strategy_id=strategy.id,
            stock_code="005930",
            stock_name="삼성전자",
            decision="BUY",
            processing_time_ms=100,
        )
        db.add(dh)
        await db.flush()

        event = TradingEvent(
            event_type="news_cluster",
            stock_code="005930",
            stock_name="삼성전자",
            event_data={"current_price": 50000},
            confidence_hint=0.7,
            status="pending",
            strategy_id=strategy.id,
            decision_history_id=dh.id,
            detected_at=_now(),
        )
        db.add(event)
        await db.flush()

        decision = EventDecisionResponse(
            decision="BUY",
            confidence=0.7,
            reasoning="테스트",
        )

        order = await execute_event_buy(
            db=db,
            strategy_id=strategy.id,
            event=event,
            decision=decision,
            decision_history=dh,
        )

        assert order is None
        assert event.status == "skipped"
