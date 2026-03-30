"""이벤트 트레이더 통합 테스트."""

from datetime import datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.models.strategy import Strategy
from app.models.system_parameter import SystemParameter
from app.models.target_stock import TargetStock
from app.models.trading_event import TradingEvent
from app.services.event_trader import (
    detect_all_events,
    has_position,
    init_event_strategy,
    is_buy_allowed,
    is_market_open,
    run_event_trader,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession, name: str = "event_trader_test") -> Strategy:
    """테스트용 전략 생성."""
    strategy = Strategy(
        name=name,
        description="테스트 전략",
        initial_capital=Decimal("10000000"),
        is_active=True,
    )
    db.add(strategy)
    await db.flush()
    # 현금 Asset 생성
    cash = Asset(
        strategy_id=strategy.id,
        stock_code=None,
        stock_name=None,
        quantity=0,
        unit_price=0,
        total_amount=float(Decimal("10000000")),
    )
    db.add(cash)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_event(
    db: AsyncSession,
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    event_type: str = "dart_disclosure",
    status: str = "pending",
    strategy_id: int | None = None,
) -> TradingEvent:
    """테스트용 이벤트 생성."""
    event = TradingEvent(
        event_type=event_type,
        stock_code=stock_code,
        stock_name=stock_name,
        event_data={"title": "테스트 이벤트", "current_price": 70000},
        confidence_hint=0.7,
        status=status,
        strategy_id=strategy_id,
        detected_at=_now(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def _create_prompt_template(
    db: AsyncSession, strategy_id: int, prompt_type: str,
) -> PromptTemplate:
    """테스트용 프롬프트 템플릿 생성."""
    template = PromptTemplate(
        strategy_id=strategy_id,
        prompt_type=prompt_type,
        content="테스트 프롬프트 {{ context_json }}",
        version=1,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    return template


# ---------------------------------------------------------------------------
# 장 운영 시간 / 매수 시간 테스트
# ---------------------------------------------------------------------------


async def test_is_market_open_during_trading_hours(db: AsyncSession):
    """장 운영 시간 내에는 True를 반환한다."""
    market_time = datetime(2026, 3, 29, 10, 30, 0)  # 10:30 KST
    assert is_market_open(now=market_time) is True


async def test_is_market_open_before_open(db: AsyncSession):
    """장 시작 전에는 False를 반환한다."""
    early = datetime(2026, 3, 29, 8, 30, 0)  # 08:30 KST
    assert is_market_open(now=early) is False


async def test_is_market_open_after_close(db: AsyncSession):
    """장 마감 후에는 False를 반환한다."""
    late = datetime(2026, 3, 29, 16, 0, 0)  # 16:00 KST
    assert is_market_open(now=late) is False


async def test_is_buy_allowed_before_cutoff(db: AsyncSession):
    """15:00 이전에는 매수 허용."""
    before = datetime(2026, 3, 29, 14, 50, 0)
    assert is_buy_allowed(now=before) is True


async def test_is_buy_allowed_after_cutoff(db: AsyncSession):
    """15:00 이후에는 매수 금지."""
    after = datetime(2026, 3, 29, 15, 10, 0)
    assert is_buy_allowed(now=after) is False


# ---------------------------------------------------------------------------
# 메인 루프 1회 실행 테스트 (이벤트 감지 -> 필터 -> 판단 -> 매수)
# ---------------------------------------------------------------------------


async def test_main_loop_single_iteration_buy(db: AsyncSession):
    """메인 루프 1회 실행: 이벤트 감지 -> 필터 통과 -> LLM BUY -> 매수 실행."""
    strategy = await _create_strategy(db, name=f"event_loop_buy_{_now().timestamp()}")
    await _create_prompt_template(db, strategy.id, "event_buy")

    # 이벤트 생성 (pending 상태)
    event = await _create_event(
        db,
        stock_code="005930",
        stock_name="삼성전자",
        strategy_id=strategy.id,
    )

    llm_response = (
        '{"decision": "BUY", "confidence": 0.8, "reasoning": "테스트", '
        '"target_return_pct": 5.0, "stop_pct": -2.0, "holding_days": 3, '
        '"event_assessment": "긍정적", "risk_factors": ["리스크1"]}'
    )

    async def fake_session_factory():
        """db fixture를 세션 팩토리처럼 사용."""
        class FakeCtx:
            async def __aenter__(self_):
                return db
            async def __aexit__(self_, *args):
                pass
        return FakeCtx()

    class FakeSessionFactory:
        def __call__(self_):
            class Ctx:
                async def __aenter__(self2):
                    return db
                async def __aexit__(self2, *args):
                    pass
            return Ctx()

    with (
        patch("app.services.event_trader.detect_all_events", new_callable=AsyncMock) as mock_detect,
        patch("app.services.event_trader.filter_events", new_callable=AsyncMock) as mock_filter,
        patch("app.services.event_trader.make_event_decision", new_callable=AsyncMock) as mock_decision,
        patch("app.services.event_trader.execute_event_buy", new_callable=AsyncMock) as mock_buy,
        patch("app.services.event_trader.is_market_open", return_value=True),
        patch("app.services.event_trader.is_buy_allowed", return_value=True),
        patch("app.services.event_trader.has_position", new_callable=AsyncMock, return_value=False),
        patch("app.services.event_trader.check_circuit_breaker", new_callable=AsyncMock) as mock_cb,
        patch("app.services.event_trader.send_telegram", new_callable=AsyncMock),
        patch("app.services.event_trader.run_liquidation_check", new_callable=AsyncMock),
        patch("app.services.event_trader.asyncio.sleep", new_callable=AsyncMock),
    ):
        from app.services.circuit_breaker import CircuitBreakerStatus

        mock_cb.return_value = CircuitBreakerStatus(
            is_active=False, reason=None, remaining_trades=5,
            daily_loss=Decimal("0"), consecutive_losses=0,
        )
        mock_detect.return_value = [event]
        mock_filter.return_value = ([event], [])

        from app.schemas.event_decision import EventDecisionResponse

        buy_decision = EventDecisionResponse(
            decision="BUY", confidence=0.8, reasoning="테스트",
            target_return_pct=5.0, stop_pct=-2.0, holding_days=3,
            event_assessment="긍정적", risk_factors=["리스크1"],
        )
        mock_decision.return_value = (buy_decision, DecisionHistory(
            strategy_id=strategy.id, stock_code="005930", stock_name="삼성전자",
            decision="BUY", processing_time_ms=100,
        ))

        mock_buy_order = OrderHistory(
            strategy_id=strategy.id, decision_history_id=1,
            stock_code="005930", stock_name="삼성전자",
            order_type="BUY", order_price=70000, order_quantity=7,
            order_total_amount=490000, result_price=70000,
            result_quantity=7, result_total_amount=490000,
        )
        mock_buy.return_value = mock_buy_order

        await run_event_trader(
            strategy_name=strategy.name,
            db_session_factory=FakeSessionFactory(),
            max_iterations=1,
        )

        mock_detect.assert_called_once()
        mock_filter.assert_called_once()
        mock_decision.assert_called_once()
        mock_buy.assert_called_once()


# ---------------------------------------------------------------------------
# 서킷브레이커 활성 시 매수 스킵 테스트
# ---------------------------------------------------------------------------


async def test_circuit_breaker_blocks_trading(db: AsyncSession):
    """서킷브레이커 활성 시 이벤트 감지/매수를 스킵한다."""
    strategy = await _create_strategy(db, name=f"event_cb_test_{_now().timestamp()}")

    class FakeSessionFactory:
        def __call__(self_):
            class Ctx:
                async def __aenter__(self2):
                    return db
                async def __aexit__(self2, *args):
                    pass
            return Ctx()

    with (
        patch("app.services.event_trader.detect_all_events", new_callable=AsyncMock) as mock_detect,
        patch("app.services.event_trader.is_market_open", return_value=True),
        patch("app.services.event_trader.has_position", new_callable=AsyncMock, return_value=False),
        patch("app.services.event_trader.check_circuit_breaker", new_callable=AsyncMock) as mock_cb,
        patch("app.services.event_trader.send_telegram", new_callable=AsyncMock),
        patch("app.services.event_trader.run_liquidation_check", new_callable=AsyncMock),
        patch("app.services.event_trader.asyncio.sleep", new_callable=AsyncMock),
    ):
        from app.services.circuit_breaker import CircuitBreakerStatus

        mock_cb.return_value = CircuitBreakerStatus(
            is_active=True,
            reason="연속 3회 손실",
            remaining_trades=0,
            daily_loss=Decimal("-300000"),
            consecutive_losses=3,
        )

        await run_event_trader(
            strategy_name=strategy.name,
            db_session_factory=FakeSessionFactory(),
            max_iterations=1,
        )

        # 서킷브레이커가 활성이면 이벤트 감지를 호출하지 않아야 함
        mock_detect.assert_not_called()


# ---------------------------------------------------------------------------
# 포지션 보유 시 청산 체크 실행 테스트
# ---------------------------------------------------------------------------


async def test_liquidation_check_called_when_position_held(db: AsyncSession):
    """보유 포지션이 있으면 청산 체크를 실행한다."""
    strategy = await _create_strategy(db, name=f"event_liq_test_{_now().timestamp()}")

    has_pos_calls = [True, True]  # 첫 번째(청산 체크용) True, 두 번째(매수 스킵용) True

    class FakeSessionFactory:
        def __call__(self_):
            class Ctx:
                async def __aenter__(self2):
                    return db
                async def __aexit__(self2, *args):
                    pass
            return Ctx()

    with (
        patch("app.services.event_trader.is_market_open", return_value=True),
        patch("app.services.event_trader.is_buy_allowed", return_value=True),
        patch("app.services.event_trader.has_position", new_callable=AsyncMock, side_effect=[True, True]),
        patch("app.services.event_trader.check_circuit_breaker", new_callable=AsyncMock) as mock_cb,
        patch("app.services.event_trader.run_liquidation_check", new_callable=AsyncMock) as mock_liq,
        patch("app.services.event_trader._get_current_price_map", new_callable=AsyncMock) as mock_price,
        patch("app.services.event_trader.send_telegram", new_callable=AsyncMock),
        patch("app.services.event_trader.asyncio.sleep", new_callable=AsyncMock),
    ):
        from app.services.circuit_breaker import CircuitBreakerStatus

        mock_cb.return_value = CircuitBreakerStatus(
            is_active=False, reason=None, remaining_trades=5,
            daily_loss=Decimal("0"), consecutive_losses=0,
        )
        mock_price.return_value = {"005930": Decimal("70000")}
        mock_liq.return_value = None  # 청산 안 함

        await run_event_trader(
            strategy_name=strategy.name,
            db_session_factory=FakeSessionFactory(),
            max_iterations=1,
        )

        # 청산 체크가 호출되었는지 확인
        mock_liq.assert_called_once()


# ---------------------------------------------------------------------------
# init-event-strategy 멱등성 테스트
# ---------------------------------------------------------------------------


async def test_init_event_strategy_creates_strategy(db: AsyncSession):
    """전략 초기화가 Strategy, Asset, PromptTemplate, SystemParameter를 생성한다."""
    name = f"init_test_{_now().timestamp()}"
    strategy = await init_event_strategy(db, strategy_name=name)

    assert strategy.name == name
    assert strategy.initial_capital == Decimal("10000000")
    assert strategy.is_active is True

    # 현금 Asset 확인
    from sqlalchemy import select
    cash_result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy.id,
            Asset.stock_code.is_(None),
        )
    )
    cash = cash_result.scalar_one_or_none()
    assert cash is not None
    assert float(cash.total_amount) == 10000000.0

    # PromptTemplate 확인
    pt_result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.strategy_id == strategy.id,
        )
    )
    templates = pt_result.scalars().all()
    types = {t.prompt_type for t in templates}
    assert "event_buy" in types
    assert "event_sell" in types


async def test_init_event_strategy_idempotent(db: AsyncSession):
    """전략 초기화를 두 번 호출해도 중복 생성되지 않는다."""
    name = f"idempotent_test_{_now().timestamp()}"
    strategy1 = await init_event_strategy(db, strategy_name=name)
    strategy2 = await init_event_strategy(db, strategy_name=name)

    assert strategy1.id == strategy2.id

    # PromptTemplate 중복 체크
    from sqlalchemy import select
    pt_result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.strategy_id == strategy1.id,
            PromptTemplate.prompt_type == "event_buy",
        )
    )
    templates = pt_result.scalars().all()
    assert len(templates) == 1

    # Asset 중복 체크
    cash_result = await db.execute(
        select(Asset).where(
            Asset.strategy_id == strategy1.id,
            Asset.stock_code.is_(None),
        )
    )
    cash_rows = cash_result.scalars().all()
    assert len(cash_rows) == 1
