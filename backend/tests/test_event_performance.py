"""이벤트 트레이더 성과 분석 및 Go/No-Go 게이트 테스트."""

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
from app.services.event_performance import (
    PerformanceMetrics,
    calculate_performance,
    check_go_no_go_gate,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession, name: str | None = None) -> Strategy:
    """테스트용 전략 생성."""
    strategy = Strategy(
        name=name or f"perf_test_{_now().timestamp()}",
        description="성과 테스트 전략",
        initial_capital=Decimal("10000000"),
        is_active=True,
    )
    db.add(strategy)
    await db.flush()
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
    strategy_id: int,
    event_type: str = "dart_disclosure",
    stock_code: str = "005930",
) -> TradingEvent:
    event = TradingEvent(
        event_type=event_type,
        stock_code=stock_code,
        stock_name="삼성전자",
        event_data={},
        status="processed",
        strategy_id=strategy_id,
        detected_at=_now(),
    )
    db.add(event)
    await db.flush()
    return event


async def _create_decision(
    db: AsyncSession,
    strategy_id: int,
    confidence: float = 0.8,
    stock_code: str = "005930",
) -> DecisionHistory:
    dh = DecisionHistory(
        strategy_id=strategy_id,
        stock_code=stock_code,
        stock_name="삼성전자",
        decision="BUY",
        parsed_decision={"confidence": confidence, "reasoning": "test"},
        processing_time_ms=100,
    )
    db.add(dh)
    await db.flush()
    return dh


async def _create_sell_order(
    db: AsyncSession,
    strategy_id: int,
    decision_history_id: int,
    profit_loss: float,
    profit_rate: float,
    event_id: int | None = None,
    profit_loss_net: float | None = None,
) -> OrderHistory:
    """SELL 주문 생성 헬퍼."""
    order = OrderHistory(
        strategy_id=strategy_id,
        decision_history_id=decision_history_id,
        stock_code="005930",
        stock_name="삼성전자",
        order_type="SELL",
        order_price=70000,
        order_quantity=10,
        order_total_amount=700000,
        result_price=70000,
        result_quantity=10,
        result_total_amount=700000,
        profit_loss=profit_loss,
        profit_rate=profit_rate,
        profit_loss_net=profit_loss_net or profit_loss,
        profit_rate_net=profit_rate,
        event_id=event_id,
    )
    db.add(order)
    await db.flush()
    return order


# ---------------------------------------------------------------------------
# 12.1 승률, PF, Kelly% 계산 정확성 테스트
# ---------------------------------------------------------------------------


async def test_performance_win_rate_pf_kelly(db: AsyncSession):
    """승률, PF, Kelly% 계산이 정확한지 검증한다."""
    strategy = await _create_strategy(db)

    # 3승 2패 생성
    wins = [(10000, 0.05), (20000, 0.10), (15000, 0.07)]
    losses = [(-8000, -0.04), (-12000, -0.06)]

    for pl, pr in wins:
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, pl, pr)

    for pl, pr in losses:
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, pl, pr)

    await db.commit()

    metrics = await calculate_performance(db, strategy.id)

    assert metrics.total_trades == 5
    assert metrics.win_count == 3
    assert metrics.loss_count == 2
    # 승률: 3/5 = 0.6
    assert abs(metrics.win_rate - 0.6) < 0.01

    # PF = total_profit / total_loss = 45000 / 20000 = 2.25
    total_profit = 10000 + 20000 + 15000
    total_loss_abs = 8000 + 12000
    expected_pf = total_profit / total_loss_abs
    assert abs(metrics.profit_factor - expected_pf) < 0.01

    # avg_profit_rate = (0.05 + 0.10 + 0.07) / 3 ≈ 0.0733
    # avg_loss_rate = (-0.04 + -0.06) / 2 = -0.05
    # Kelly = W - (1-W) / (avg_win / avg_loss) = 0.6 - 0.4 / (0.0733/0.05)
    avg_win = (0.05 + 0.10 + 0.07) / 3
    avg_loss = (0.04 + 0.06) / 2
    expected_kelly = 0.6 - 0.4 / (avg_win / avg_loss)
    assert abs(metrics.kelly_pct - expected_kelly) < 0.01

    # avg_profit_rate, avg_loss_rate
    assert abs(metrics.avg_profit_rate - avg_win) < 0.001
    assert abs(metrics.avg_loss_rate - (-avg_loss)) < 0.001


# ---------------------------------------------------------------------------
# 12.1.1 이벤트 유형별 그룹핑 테스트
# ---------------------------------------------------------------------------


async def test_performance_by_event_type(db: AsyncSession):
    """이벤트 유형별 성과가 올바르게 그룹핑된다."""
    strategy = await _create_strategy(db)

    # dart_disclosure 이벤트: 2건 (1승 1패)
    ev_dart1 = await _create_event(db, strategy.id, event_type="dart_disclosure")
    ev_dart2 = await _create_event(db, strategy.id, event_type="dart_disclosure")

    # news_cluster 이벤트: 1건 (1승)
    ev_news = await _create_event(db, strategy.id, event_type="news_cluster")

    dh1 = await _create_decision(db, strategy.id)
    await _create_sell_order(db, strategy.id, dh1.id, 10000, 0.05, event_id=ev_dart1.id)

    dh2 = await _create_decision(db, strategy.id)
    await _create_sell_order(db, strategy.id, dh2.id, -5000, -0.03, event_id=ev_dart2.id)

    dh3 = await _create_decision(db, strategy.id)
    await _create_sell_order(db, strategy.id, dh3.id, 8000, 0.04, event_id=ev_news.id)

    await db.commit()

    metrics = await calculate_performance(db, strategy.id)

    assert "dart_disclosure" in metrics.by_event_type
    assert "news_cluster" in metrics.by_event_type

    dart = metrics.by_event_type["dart_disclosure"]
    assert dart.total_trades == 2
    assert dart.win_count == 1
    assert dart.loss_count == 1
    assert abs(dart.win_rate - 0.5) < 0.01

    news = metrics.by_event_type["news_cluster"]
    assert news.total_trades == 1
    assert news.win_count == 1
    assert abs(news.win_rate - 1.0) < 0.01


# ---------------------------------------------------------------------------
# 12.1.2 Confidence 구간별 그룹핑 테스트
# ---------------------------------------------------------------------------


async def test_performance_by_confidence_bucket(db: AsyncSession):
    """Confidence 구간별 성과가 올바르게 그룹핑된다."""
    strategy = await _create_strategy(db)

    # confidence 0.8 (0.7-1.0 구간) → 승
    dh1 = await _create_decision(db, strategy.id, confidence=0.8)
    await _create_sell_order(db, strategy.id, dh1.id, 10000, 0.05)

    # confidence 0.4 (0.3-0.5 구간) → 패
    dh2 = await _create_decision(db, strategy.id, confidence=0.4)
    await _create_sell_order(db, strategy.id, dh2.id, -5000, -0.03)

    # confidence 0.6 (0.5-0.7 구간) → 승
    dh3 = await _create_decision(db, strategy.id, confidence=0.6)
    await _create_sell_order(db, strategy.id, dh3.id, 8000, 0.04)

    # confidence 0.2 (0.0-0.3 구간) → 패
    dh4 = await _create_decision(db, strategy.id, confidence=0.2)
    await _create_sell_order(db, strategy.id, dh4.id, -3000, -0.02)

    await db.commit()

    metrics = await calculate_performance(db, strategy.id)

    assert "0.7-1.0" in metrics.by_confidence_bucket
    bucket_high = metrics.by_confidence_bucket["0.7-1.0"]
    assert bucket_high.total_trades == 1
    assert bucket_high.win_count == 1

    assert "0.3-0.5" in metrics.by_confidence_bucket
    bucket_mid = metrics.by_confidence_bucket["0.3-0.5"]
    assert bucket_mid.total_trades == 1
    assert bucket_mid.loss_count == 1

    assert "0.5-0.7" in metrics.by_confidence_bucket
    bucket_mid_high = metrics.by_confidence_bucket["0.5-0.7"]
    assert bucket_mid_high.total_trades == 1
    assert bucket_mid_high.win_count == 1

    assert "0.0-0.3" in metrics.by_confidence_bucket
    bucket_low = metrics.by_confidence_bucket["0.0-0.3"]
    assert bucket_low.total_trades == 1
    assert bucket_low.loss_count == 1


# ---------------------------------------------------------------------------
# 12.2 Go/No-Go 20건 게이트 테스트 (PF < 0.5 → 실패)
# ---------------------------------------------------------------------------


async def test_gate_20_fail_low_pf(db: AsyncSession):
    """20건 게이트: PF < 0.5이면 실패 + 즉시 중단 권고."""
    strategy = await _create_strategy(db)

    # 20건 생성: 3승 17패 → 승률 15%, PF 매우 낮음
    for i in range(3):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 5000, 0.02)
    for i in range(17):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -10000, -0.05)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "20"
    assert gate.passed is False
    assert gate.recommendation == "stop"
    assert gate.details["profit_factor"] < 0.5


async def test_gate_20_fail_low_win_rate(db: AsyncSession):
    """20건 게이트: 승률 < 15%이면 실패."""
    strategy = await _create_strategy(db)

    # 20건: 2승 18패 → 승률 10%
    for i in range(2):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 50000, 0.25)
    for i in range(18):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -3000, -0.02)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "20"
    assert gate.passed is False
    assert gate.details["win_rate"] < 0.15


async def test_gate_20_pass(db: AsyncSession):
    """20건 게이트: PF >= 0.5 AND 승률 >= 15%이면 통과."""
    strategy = await _create_strategy(db)

    # 20건: 8승 12패 → 승률 40%, PF 적당
    for i in range(8):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 10000, 0.05)
    for i in range(12):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -5000, -0.03)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "20"
    assert gate.passed is True
    assert gate.recommendation == "continue"


# ---------------------------------------------------------------------------
# 12.2 Go/No-Go 50건 게이트 테스트
# ---------------------------------------------------------------------------


async def test_gate_50_pass(db: AsyncSession):
    """50건 게이트: 모든 조건 충족 시 통과."""
    strategy = await _create_strategy(db)

    # 50건: 25승 25패, 승률 50%, PF > 1.2, Kelly > 0.05
    # PF = total_profit / total_loss ≥ 1.2 → profit 큰 승, loss 작은 패
    for i in range(25):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 15000, 0.08)
    for i in range(25):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "50"
    assert gate.passed is True
    assert gate.recommendation == "continue"


async def test_gate_50_fail(db: AsyncSession):
    """50건 게이트: PF < 1.2 → 실패 + review 권고."""
    strategy = await _create_strategy(db)

    # 50건: 20승 30패, PF < 1.2
    for i in range(20):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 8000, 0.04)
    for i in range(30):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "50"
    assert gate.passed is False
    # 첫 실패이므로 review
    assert gate.recommendation == "review"


# ---------------------------------------------------------------------------
# 12.2 Go/No-Go 100건 게이트 테스트 (전반/후반 괴리)
# ---------------------------------------------------------------------------


async def test_gate_100_pass_low_divergence(db: AsyncSession):
    """100건 게이트: 전반/후반 괴리 < 30%이면 통과."""
    strategy = await _create_strategy(db)

    # 전반 50건: 25승 25패 (승률 50%)
    for i in range(25):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 10000, 0.05)
    for i in range(25):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    # 후반 50건: 23승 27패 (승률 46%) → 괴리 = |0.5-0.46|/0.5 = 0.08 < 0.30
    for i in range(23):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 10000, 0.05)
    for i in range(27):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "100"
    assert gate.passed is True
    assert gate.recommendation == "continue"
    assert gate.details["divergence"] < 0.30


async def test_gate_100_fail_high_divergence(db: AsyncSession):
    """100건 게이트: 전반/후반 괴리 >= 30%이면 실패."""
    strategy = await _create_strategy(db)

    # 전반 50건: 35승 15패 (승률 70%)
    for i in range(35):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 10000, 0.05)
    for i in range(15):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    # 후반 50건: 10승 40패 (승률 20%) → 괴리 = |0.7-0.2|/0.7 = 0.714 > 0.30
    for i in range(10):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, 10000, 0.05)
    for i in range(40):
        dh = await _create_decision(db, strategy.id)
        await _create_sell_order(db, strategy.id, dh.id, -8000, -0.04)

    await db.commit()

    gate = await check_go_no_go_gate(db, strategy.id)
    assert gate is not None
    assert gate.gate_level == "100"
    assert gate.passed is False
    assert gate.recommendation == "review"
    assert gate.details["divergence"] >= 0.30
