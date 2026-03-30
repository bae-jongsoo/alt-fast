"""서킷브레이커 — 연속 손실, 일일 손실 한도, 일일 매매 상한 안전장치."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order_history import OrderHistory
from app.models.strategy import Strategy
from app.services.param_helper import get_param

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# ── 기본값 ──────────────────────────────────────────────────────────
DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
DEFAULT_DAILY_LOSS_LIMIT_PCT = Decimal("3.0")
DEFAULT_MAX_DAILY_TRADES = 5


@dataclass
class CircuitBreakerStatus:
    is_active: bool  # True면 매매 차단
    reason: str | None
    remaining_trades: int  # 남은 매매 가능 횟수
    daily_loss: Decimal  # 금일 누적 손실
    consecutive_losses: int


# ── 연속 손실 카운트 ─────────────────────────────────────────────────

async def _count_consecutive_losses(db: AsyncSession, strategy_id: int) -> int:
    """해당 전략의 최근 SELL 주문에서 연속 손실 건수를 카운트한다.
    마지막 수익 매매 이후 연속 손실만 카운트.
    """
    result = await db.execute(
        select(OrderHistory.profit_loss)
        .where(
            OrderHistory.strategy_id == strategy_id,
            OrderHistory.order_type == "SELL",
        )
        .order_by(OrderHistory.created_at.desc())
    )
    rows = result.scalars().all()

    count = 0
    for pl in rows:
        if pl is not None and Decimal(str(pl)) < 0:
            count += 1
        else:
            break
    return count


# ── 일일 손실 합계 ──────────────────────────────────────────────────

async def _get_daily_loss(db: AsyncSession, strategy_id: int) -> Decimal:
    """당일(KST) SELL 주문의 profit_loss_net 합계 (손실은 음수)."""
    today_kst = datetime.now(KST).date()
    # KST 오늘 00:00 → UTC
    start_of_day = datetime(today_kst.year, today_kst.month, today_kst.day, tzinfo=KST)
    start_utc = start_of_day.replace(tzinfo=None) - timedelta(hours=9)

    result = await db.execute(
        select(func.coalesce(func.sum(OrderHistory.profit_loss_net), 0))
        .where(
            OrderHistory.strategy_id == strategy_id,
            OrderHistory.order_type == "SELL",
            OrderHistory.created_at >= start_utc,
        )
    )
    total = result.scalar_one()
    return Decimal(str(total))


# ── 일일 매매 건수 ──────────────────────────────────────────────────

async def _get_daily_trade_count(db: AsyncSession, strategy_id: int) -> int:
    """당일(KST) BUY 주문 건수."""
    today_kst = datetime.now(KST).date()
    start_of_day = datetime(today_kst.year, today_kst.month, today_kst.day, tzinfo=KST)
    start_utc = start_of_day.replace(tzinfo=None) - timedelta(hours=9)

    result = await db.execute(
        select(func.count())
        .select_from(OrderHistory)
        .where(
            OrderHistory.strategy_id == strategy_id,
            OrderHistory.order_type == "BUY",
            OrderHistory.created_at >= start_utc,
        )
    )
    return result.scalar_one()


# ── 메인 체크 ────────────────────────────────────────────────────────

async def check_circuit_breaker(
    db: AsyncSession,
    strategy_id: int,
) -> CircuitBreakerStatus:
    """서킷브레이커 상태를 조회한다."""
    # 파라미터 로드
    max_consecutive = int(
        await get_param(db, "cb_max_consecutive_losses", str(DEFAULT_MAX_CONSECUTIVE_LOSSES), strategy_id=strategy_id)
    )
    daily_loss_limit_pct = Decimal(
        await get_param(db, "cb_daily_loss_limit_pct", str(DEFAULT_DAILY_LOSS_LIMIT_PCT), strategy_id=strategy_id)
    )
    max_daily_trades = int(
        await get_param(db, "cb_max_daily_trades", str(DEFAULT_MAX_DAILY_TRADES), strategy_id=strategy_id)
    )

    # 전략의 initial_capital 조회
    result = await db.execute(
        select(Strategy.initial_capital).where(Strategy.id == strategy_id)
    )
    initial_capital = result.scalar_one_or_none()
    if initial_capital is None:
        raise ValueError(f"전략을 찾을 수 없습니다 (strategy_id={strategy_id})")
    initial_capital = Decimal(str(initial_capital))

    # 각 조건 계산
    consecutive_losses = await _count_consecutive_losses(db, strategy_id)
    daily_loss = await _get_daily_loss(db, strategy_id)
    daily_trade_count = await _get_daily_trade_count(db, strategy_id)

    remaining_trades = max(0, max_daily_trades - daily_trade_count)

    # 서킷브레이커 판단
    reason = None

    # 1) 연속 손실 체크
    if consecutive_losses >= max_consecutive:
        reason = f"연속 {consecutive_losses}회 손실 (한도: {max_consecutive}회)"

    # 2) 일일 손실 한도 체크
    loss_limit = initial_capital * daily_loss_limit_pct / Decimal("100")
    if daily_loss < 0 and abs(daily_loss) >= loss_limit:
        loss_reason = (
            f"일일 손실 {daily_loss:,.0f}원 "
            f"(한도: -{loss_limit:,.0f}원, 총자산의 {daily_loss_limit_pct}%)"
        )
        reason = loss_reason if reason is None else f"{reason} / {loss_reason}"

    # 3) 일일 매매 상한 체크
    if daily_trade_count >= max_daily_trades:
        trade_reason = f"일일 매매 {daily_trade_count}건 (한도: {max_daily_trades}건)"
        reason = trade_reason if reason is None else f"{reason} / {trade_reason}"

    is_active = reason is not None

    return CircuitBreakerStatus(
        is_active=is_active,
        reason=reason,
        remaining_trades=remaining_trades,
        daily_loss=daily_loss,
        consecutive_losses=consecutive_losses,
    )


# ── 수동 리셋 ────────────────────────────────────────────────────────

async def reset_circuit_breaker(
    db: AsyncSession,
    strategy_id: int,
) -> CircuitBreakerStatus:
    """서킷브레이커를 수동 해제한다.

    Redis 캐시를 초기화하고 현재 상태를 반환한다.
    연속 손실 리셋은 DB에 직접 개입하지 않으므로,
    Redis 캐시만 클리어하여 다음 체크에서 재평가하도록 한다.
    실질적으로 연속 손실 카운트는 DB 기반이므로,
    리셋은 Redis 기반 차단 해제 + 상태 재조회를 의미한다.
    """
    try:
        from app.services.ws_collector import get_redis

        redis = await get_redis()
        key = f"circuit_breaker:{strategy_id}"
        await redis.delete(key)
        logger.info("서킷브레이커 Redis 캐시 초기화: strategy_id=%d", strategy_id)
    except Exception:
        logger.warning("Redis 서킷브레이커 캐시 초기화 실패 (무시)", exc_info=True)

    return await check_circuit_breaker(db, strategy_id)
