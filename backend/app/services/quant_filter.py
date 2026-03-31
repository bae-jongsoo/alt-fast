"""퀀트 필터 서비스.

이벤트 감지 모듈이 생성한 이벤트를 LLM 호출 전에 룰 기반으로 필터링한다.
거래량, 호가 스프레드, 시총 등을 체크하여 매매 부적합 종목을 사전에 걸러낸다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.models.trading_event import TradingEvent
from app.services.param_helper import get_param

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 시스템 파라미터 키 및 기본값
_PARAM_DEFAULTS: dict[str, str] = {
    "quant_filter_min_volume_ratio": "2.0",
    "quant_filter_max_spread_pct": "0.5",
    "quant_filter_min_market_cap": "50000000000",
    "quant_filter_min_price": "1000",
}


@dataclass
class FilterResult:
    passed: bool
    reason: str | None = None
    metrics: dict = field(default_factory=dict)


async def _check_volume(
    db: AsyncSession, stock_code: str, min_volume_ratio: float,
) -> tuple[bool, str | None, dict]:
    """당일 거래량 >= 전일 평균의 min_volume_ratio 배인지 검사."""
    now = datetime.now(KST).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start

    # 당일 누적 거래량
    today_vol_stmt = (
        select(func.sum(MinuteCandle.volume))
        .where(
            MinuteCandle.stock_code == stock_code,
            MinuteCandle.minute_at >= today_start,
        )
    )
    today_result = await db.execute(today_vol_stmt)
    today_volume = today_result.scalar_one_or_none()
    today_volume = int(today_volume) if today_volume else 0

    # 전일 평균 거래량 (전일 전체 분봉의 합계를 1일 기준으로)
    prev_vol_stmt = (
        select(func.sum(MinuteCandle.volume))
        .where(
            MinuteCandle.stock_code == stock_code,
            MinuteCandle.minute_at >= yesterday_start,
            MinuteCandle.minute_at < yesterday_end,
        )
    )
    prev_result = await db.execute(prev_vol_stmt)
    prev_volume = prev_result.scalar_one_or_none()
    prev_volume = int(prev_volume) if prev_volume else 0

    metrics = {
        "today_volume": today_volume,
        "prev_day_volume": prev_volume,
        "min_volume_ratio": min_volume_ratio,
    }

    if prev_volume <= 0:
        # 전일 데이터 없으면 필터 패스
        metrics["volume_ratio"] = None
        return True, None, metrics

    ratio = today_volume / prev_volume
    metrics["volume_ratio"] = round(ratio, 4)

    if ratio < min_volume_ratio:
        return False, f"거래량 부족: {ratio:.2f}배 (기준: {min_volume_ratio}배)", metrics
    return True, None, metrics


async def _check_spread(
    db: AsyncSession, stock_code: str, max_spread_pct: float,
) -> tuple[bool, str | None, dict]:
    """최신 호가 스프레드가 max_spread_pct% 이하인지 검사."""
    stmt = (
        select(OrderbookSnapshot)
        .where(OrderbookSnapshot.stock_code == stock_code)
        .order_by(OrderbookSnapshot.snapshot_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    ob = result.scalar_one_or_none()

    metrics: dict = {"max_spread_pct": max_spread_pct}

    if ob is None:
        # 호가 데이터 없으면 필터 패스
        metrics["spread_pct"] = None
        return True, None, metrics

    ask1 = ob.ask_price1
    bid1 = ob.bid_price1
    mid = (ask1 + bid1) / 2
    if mid <= 0:
        metrics["spread_pct"] = None
        return True, None, metrics

    spread_pct = (ask1 - bid1) / mid * 100
    metrics["spread_pct"] = round(spread_pct, 4)
    metrics["ask_price1"] = ask1
    metrics["bid_price1"] = bid1

    if spread_pct > max_spread_pct:
        return False, f"호가 스프레드 과다: {spread_pct:.2f}% (기준: {max_spread_pct}%)", metrics
    return True, None, metrics


async def _check_market_cap(
    db: AsyncSession, stock_code: str, min_market_cap: int,
) -> tuple[bool, str | None, dict]:
    """시가총액이 min_market_cap 이상인지 검사."""
    stmt = (
        select(MarketSnapshot)
        .where(MarketSnapshot.stock_code == stock_code)
        .order_by(MarketSnapshot.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    ms = result.scalar_one_or_none()

    metrics: dict = {"min_market_cap": min_market_cap}

    if ms is None or ms.hts_avls is None:
        metrics["market_cap"] = None
        return True, None, metrics

    market_cap = ms.hts_avls
    metrics["market_cap"] = market_cap

    if market_cap < min_market_cap:
        return (
            False,
            f"시총 부족: {market_cap:,}원 (기준: {min_market_cap:,}원)",
            metrics,
        )
    return True, None, metrics


async def _check_price(
    db: AsyncSession, stock_code: str, min_price: int,
) -> tuple[bool, str | None, dict]:
    """주가가 min_price 이상인지 검사. MinuteCandle 최신 close 사용."""
    stmt = (
        select(MinuteCandle.close)
        .where(MinuteCandle.stock_code == stock_code)
        .order_by(MinuteCandle.minute_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    price = result.scalar_one_or_none()

    metrics: dict = {"min_price": min_price}

    if price is None:
        metrics["current_price"] = None
        return True, None, metrics

    metrics["current_price"] = price

    if price < min_price:
        return False, f"주가 부족: {price:,}원 (기준: {min_price:,}원)", metrics
    return True, None, metrics


async def _check_trading_halt(
    db: AsyncSession, stock_code: str,
) -> tuple[bool, str | None, dict]:
    """거래정지 여부 검사. MarketSnapshot의 temp_stop_yn 필드."""
    stmt = (
        select(MarketSnapshot)
        .where(MarketSnapshot.stock_code == stock_code)
        .order_by(MarketSnapshot.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    ms = result.scalar_one_or_none()

    metrics: dict = {}

    if ms is None:
        metrics["temp_stop_yn"] = None
        return True, None, metrics

    metrics["temp_stop_yn"] = ms.temp_stop_yn

    if ms.temp_stop_yn == "Y":
        return False, "거래정지 종목", metrics
    return True, None, metrics


async def _check_existing_position(
    db: AsyncSession, stock_code: str, strategy_id: int,
) -> tuple[bool, str | None, dict]:
    """해당 전략에 동일 종목 포지션 보유 여부 검사."""
    stmt = (
        select(Asset)
        .where(
            Asset.strategy_id == strategy_id,
            Asset.stock_code == stock_code,
            Asset.quantity > 0,
        )
    )
    result = await db.execute(stmt)
    asset = result.scalar_one_or_none()

    metrics: dict = {}

    if asset is not None:
        metrics["existing_quantity"] = asset.quantity
        return False, f"기존 포지션 보유: {asset.quantity}주", metrics

    metrics["existing_quantity"] = 0
    return True, None, metrics


async def apply_quant_filter(
    db: AsyncSession, event: TradingEvent,
) -> FilterResult:
    """이벤트에 퀀트 필터를 적용한다. 모든 조건을 통과해야 passed=True."""
    # 시스템 파라미터 로드
    sid = event.strategy_id
    min_volume_ratio = float(await get_param(db, "quant_filter_min_volume_ratio", _PARAM_DEFAULTS["quant_filter_min_volume_ratio"], strategy_id=sid))
    max_spread_pct = float(await get_param(db, "quant_filter_max_spread_pct", _PARAM_DEFAULTS["quant_filter_max_spread_pct"], strategy_id=sid))
    min_market_cap = int(await get_param(db, "quant_filter_min_market_cap", _PARAM_DEFAULTS["quant_filter_min_market_cap"], strategy_id=sid))
    min_price = int(await get_param(db, "quant_filter_min_price", _PARAM_DEFAULTS["quant_filter_min_price"], strategy_id=sid))

    all_metrics: dict = {}
    stock_code = event.stock_code
    strategy_id = event.strategy_id

    # 필터 순서대로 실행 (하나라도 실패하면 즉시 반환)
    # 거래량 필터는 제외 — 대형 타겟 종목 대상이라 LLM 컨텍스트로 대체
    filter_specs: list[tuple[str, tuple]] = [
        ("spread", (stock_code, max_spread_pct)),
        ("market_cap", (stock_code, min_market_cap)),
        ("price", (stock_code, min_price)),
        ("trading_halt", (stock_code,)),
    ]
    filter_funcs = {
        "spread": _check_spread,
        "market_cap": _check_market_cap,
        "price": _check_price,
        "trading_halt": _check_trading_halt,
    }

    for name, args in filter_specs:
        passed, reason, metrics = await filter_funcs[name](db, *args)
        all_metrics[name] = metrics
        if not passed:
            return FilterResult(passed=False, reason=reason, metrics=all_metrics)

    # 포지션 체크 (strategy_id가 있는 경우만)
    if strategy_id is not None:
        passed, reason, metrics = await _check_existing_position(
            db, stock_code, strategy_id,
        )
        all_metrics["position"] = metrics
        if not passed:
            return FilterResult(passed=False, reason=reason, metrics=all_metrics)

    return FilterResult(passed=True, reason=None, metrics=all_metrics)


async def filter_events(
    db: AsyncSession,
    events: list[TradingEvent],
    strategy_id: int,
) -> tuple[list[TradingEvent], list[TradingEvent]]:
    """이벤트 목록에 퀀트 필터를 배치 적용한다.

    Returns:
        (passed_events, filtered_events)
        필터링된 이벤트는 status='filtered'로 업데이트하고 reason 기록.
    """
    passed_events: list[TradingEvent] = []
    filtered_events: list[TradingEvent] = []

    for event in events:
        # strategy_id 설정
        event.strategy_id = strategy_id

        result = await apply_quant_filter(db, event)

        # event_data에 filter_result 기록
        event_data = event.event_data or {}
        event_data["filter_result"] = {
            "passed": result.passed,
            "reason": result.reason,
            "metrics": result.metrics,
        }
        event.event_data = event_data

        if result.passed:
            passed_events.append(event)
        else:
            event.status = "filtered"
            event.processed_at = datetime.now(KST).replace(tzinfo=None)
            filtered_events.append(event)

    await db.commit()

    return passed_events, filtered_events
