"""이벤트 트레이더 관련 API 엔드포인트."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.trading_event import TradingEvent
from app.services.circuit_breaker import check_circuit_breaker, reset_circuit_breaker
from app.services.event_performance import (
    calculate_performance,
    check_go_no_go_gate,
)

router = APIRouter(prefix="/api/event-trader", tags=["event-trader"])


# ── 성과 API ──────────────────────────────────────────────────────────


@router.get("/performance")
async def get_performance(
    strategy_id: int = Query(..., ge=1),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """전체 성과 지표 조회."""
    metrics = await calculate_performance(db, strategy_id, start_date, end_date)
    return {
        "total_trades": metrics.total_trades,
        "win_count": metrics.win_count,
        "loss_count": metrics.loss_count,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "kelly_pct": metrics.kelly_pct,
        "avg_profit_rate": metrics.avg_profit_rate,
        "avg_loss_rate": metrics.avg_loss_rate,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "sharpe_ratio": metrics.sharpe_ratio,
    }


@router.get("/performance/by-event-type")
async def get_performance_by_event_type(
    strategy_id: int = Query(..., ge=1),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """이벤트 유형별 성과 조회."""
    metrics = await calculate_performance(db, strategy_id, start_date, end_date)
    return {
        et: {
            "event_type": m.event_type,
            "total_trades": m.total_trades,
            "win_count": m.win_count,
            "loss_count": m.loss_count,
            "win_rate": m.win_rate,
            "avg_profit_rate": m.avg_profit_rate,
            "profit_factor": m.profit_factor,
        }
        for et, m in metrics.by_event_type.items()
    }


@router.get("/performance/by-confidence")
async def get_performance_by_confidence(
    strategy_id: int = Query(..., ge=1),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """Confidence 구간별 성과 조회."""
    metrics = await calculate_performance(db, strategy_id, start_date, end_date)
    return {
        bucket: {
            "bucket": m.bucket,
            "total_trades": m.total_trades,
            "win_count": m.win_count,
            "loss_count": m.loss_count,
            "win_rate": m.win_rate,
            "avg_profit_rate": m.avg_profit_rate,
        }
        for bucket, m in metrics.by_confidence_bucket.items()
    }


# ── 이벤트 목록 API ──────────────────────────────────────────────────


@router.get("/events")
async def get_events(
    strategy_id: int = Query(None, ge=1),
    status: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """최근 이벤트 목록 조회."""
    query = select(TradingEvent).order_by(TradingEvent.detected_at.desc()).limit(limit)
    if strategy_id:
        query = query.where(TradingEvent.strategy_id == strategy_id)
    if status:
        query = query.where(TradingEvent.status == status)
    if event_type:
        query = query.where(TradingEvent.event_type == event_type)

    result = await db.execute(query)
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "stock_code": e.stock_code,
            "stock_name": e.stock_name,
            "status": e.status,
            "confidence_hint": float(e.confidence_hint) if e.confidence_hint else None,
            "detected_at": e.detected_at.isoformat() if e.detected_at else None,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
        }
        for e in events
    ]


# ── Go/No-Go 게이트 API ──────────────────────────────────────────────


@router.get("/gate")
async def get_gate_status(
    strategy_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """Go/No-Go 게이트 상태 조회."""
    gate = await check_go_no_go_gate(db, strategy_id)
    if gate is None:
        return {
            "gate_level": None,
            "passed": None,
            "details": {"message": "아직 게이트 레벨(20건)에 도달하지 않았습니다."},
            "recommendation": None,
        }
    return {
        "gate_level": gate.gate_level,
        "passed": gate.passed,
        "details": gate.details,
        "recommendation": gate.recommendation,
    }


# ── 서킷브레이커 API ─────────────────────────────────────────────────


@router.get("/circuit-breaker/status")
async def get_circuit_breaker_status(
    strategy_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """서킷브레이커 상태 조회."""
    status = await check_circuit_breaker(db, strategy_id)
    return {
        "is_active": status.is_active,
        "reason": status.reason,
        "remaining_trades": status.remaining_trades,
        "daily_loss": float(status.daily_loss),
        "consecutive_losses": status.consecutive_losses,
    }


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker_endpoint(
    strategy_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """서킷브레이커 수동 리셋."""
    status = await reset_circuit_breaker(db, strategy_id)
    return {
        "is_active": status.is_active,
        "reason": status.reason,
        "remaining_trades": status.remaining_trades,
        "daily_loss": float(status.daily_loss),
        "consecutive_losses": status.consecutive_losses,
    }
