"""보고서 서비스 분석 항목 — 놓친 기회, 시간대별, HOLD 복기, 변동성, 벤치마크, 반복매매, 빈도, 매수가."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, time as dt_time
from typing import Sequence

from sqlalchemy import select, and_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.decision_history import DecisionHistory
from app.models.minute_candle import MinuteCandle
from app.models.order_history import OrderHistory
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.models.target_stock import TargetStock
from app.schemas.report import (
    BenchmarkComparison,
    EntryQualityItem,
    HoldReviewItem_41,
    HoldReviewItem_42,
    HoldReviewSummary,
    InactiveZoneStats,
    InactiveZoneStockDetail,
    MissedOpportunityItem,
    RepeatedTradeItem,
    TimeZoneStats,
    TradeFrequencyStats,
    VolatilityCaptureItem,
)

# ── 유틸리티 ─────────────────────────────────────────────────────


def _date_range(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


_TIME_ZONES: list[tuple[str, dt_time, dt_time]] = [
    ("장초반", dt_time(9, 11), dt_time(9, 30)),
    ("오전장", dt_time(9, 30), dt_time(11, 30)),
    ("점심", dt_time(11, 30), dt_time(13, 0)),
    ("오후장", dt_time(13, 0), dt_time(14, 30)),
    ("마감접근", dt_time(14, 30), dt_time(15, 20)),
    ("동시호가", dt_time(15, 20), dt_time(15, 31)),
]


def _classify_time_zone(dt: datetime) -> str:
    t = dt.time()
    for name, start, end in _TIME_ZONES:
        if start <= t < end:
            return name
    return "장외"


async def _get_buy_sell_pairs(
    db: AsyncSession, target_date: date
) -> list[tuple[OrderHistory, OrderHistory]]:
    """해당일 BUY-SELL 페어를 반환한다."""
    start, end = _date_range(target_date)
    BuyOrder = aliased(OrderHistory)

    stmt = (
        select(OrderHistory, BuyOrder)
        .outerjoin(BuyOrder, OrderHistory.buy_order_id == BuyOrder.id)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
            )
        )
        .order_by(OrderHistory.result_executed_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [(sell, buy) for sell, buy in rows if buy is not None]


async def _get_candles_for_stock_date(
    db: AsyncSession,
    stock_code: str,
    target_date: date,
) -> list[MinuteCandle]:
    start, end = _date_range(target_date)
    stmt = (
        select(MinuteCandle)
        .where(
            and_(
                MinuteCandle.stock_code == stock_code,
                MinuteCandle.minute_at >= start,
                MinuteCandle.minute_at < end,
            )
        )
        .order_by(MinuteCandle.minute_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _get_candles_in_range(
    db: AsyncSession,
    stock_code: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[MinuteCandle]:
    stmt = (
        select(MinuteCandle)
        .where(
            and_(
                MinuteCandle.stock_code == stock_code,
                MinuteCandle.minute_at >= start_dt,
                MinuteCandle.minute_at <= end_dt,
            )
        )
        .order_by(MinuteCandle.minute_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _get_active_target_stocks(db: AsyncSession) -> list[TargetStock]:
    stmt = select(TargetStock).where(TargetStock.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── #2: 놓친 기회 분석 ──────────────────────────────────────────


def _capture_grade(capture_rate: float, holding_seconds: float) -> str:
    """보유시간별 동적 기준으로 캡처 등급 판정."""
    if holding_seconds <= 600:  # ~10분
        threshold = 30.0
    elif holding_seconds <= 1800:  # ~30분
        threshold = 45.0
    elif holding_seconds <= 3600:  # ~1시간
        threshold = 55.0
    else:
        threshold = 70.0

    if capture_rate >= threshold:
        return "우수"
    elif capture_rate >= threshold * 0.5:
        return "보통"
    else:
        return "미흡"


def _quality_verdict(
    capture_rate: float | None,
    capture_grade: str | None,
    hold_mdd: float | None,
) -> str:
    """캡처율 + MDD 조합 판정."""
    if capture_rate is None:
        return "판정불가"

    good_capture = capture_grade == "우수"
    low_mdd = (hold_mdd or 0) < 3.0

    if good_capture and low_mdd:
        return "우수"
    elif good_capture or low_mdd:
        return "보통"
    else:
        return "미흡"


async def analyze_missed_opportunities(
    db: AsyncSession, target_date: date
) -> list[MissedOpportunityItem]:
    pairs = await _get_buy_sell_pairs(db, target_date)
    if not pairs:
        return []

    items: list[MissedOpportunityItem] = []
    for sell, buy in pairs:
        buy_price = float(buy.result_price)
        sell_price = float(sell.result_price)
        buy_at = buy.result_executed_at
        sell_at = sell.result_executed_at

        holding_seconds: float | None = None
        if buy_at and sell_at:
            holding_seconds = (sell_at - buy_at).total_seconds()

        # 보유 구간 분봉 조회 (분봉은 분 시작 기준이므로 초를 잘라서 확장)
        candles: list[MinuteCandle] = []
        if buy_at and sell_at:
            candle_start = buy_at.replace(second=0, microsecond=0)
            candle_end = sell_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
            candles = await _get_candles_in_range(
                db, sell.stock_code, candle_start, candle_end
            )

        # 당일 전체 분봉 (저점 회피율 계산용)
        day_candles = await _get_candles_for_stock_date(
            db, sell.stock_code, target_date
        )

        peak_price: float | None = None
        trough_price: float | None = None
        capture_rate: float | None = None
        hold_mdd: float | None = None
        trough_avoidance: float | None = None
        grade: str | None = None

        if candles:
            peak_price = float(max(c.high for c in candles))
            trough_price = float(min(c.low for c in candles))

            # 고점 캡처율
            if peak_price > buy_price:
                capture_rate = (
                    (sell_price - buy_price) / (peak_price - buy_price) * 100
                )
            elif sell_price >= buy_price:
                capture_rate = 100.0
            else:
                capture_rate = 0.0

            # 보유 중 MDD
            if buy_price > 0:
                hold_mdd = (buy_price - trough_price) / buy_price * 100

            grade = _capture_grade(
                capture_rate, holding_seconds or 0
            )

        # 저점 회피율
        if day_candles and trough_price is not None:
            day_high = float(max(c.high for c in day_candles))
            day_low = float(min(c.low for c in day_candles))
            if day_high != day_low:
                trough_avoidance = (
                    (buy_price - trough_price) / (day_high - day_low)
                )

        # 조기 청산 체크 (매도 후 10분 내 상승 여부)
        early_exit = False
        early_exit_upside: float | None = None
        if sell_at:
            post_candles = await _get_candles_in_range(
                db,
                sell.stock_code,
                sell_at,
                sell_at + timedelta(minutes=10),
            )
            if post_candles:
                post_high = float(max(c.high for c in post_candles))
                if post_high > sell_price and sell_price > 0:
                    upside = (post_high - sell_price) / sell_price * 100
                    if upside > 0.5:  # 0.5% 이상 상승 시 조기 청산
                        early_exit = True
                        early_exit_upside = upside

        # LLM 가격 정확도 (진입 속도 보완 ④)
        llm_price_accuracy: float | None = None
        decision_stmt = (
            select(DecisionHistory)
            .where(DecisionHistory.id == buy.decision_history_id)
        )
        dec_result = await db.execute(decision_stmt)
        decision = dec_result.scalar_one_or_none()
        if decision and decision.parsed_decision:
            parsed = decision.parsed_decision
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except (json.JSONDecodeError, TypeError):
                    parsed = None
            if parsed and isinstance(parsed, dict):
                dec_data = parsed.get("decision", parsed)
                if isinstance(dec_data, dict):
                    llm_price = dec_data.get("price")
                    if llm_price and buy_at:
                        # 해당 분봉 종가 비교
                        candle_at_buy = await _get_candles_in_range(
                            db,
                            sell.stock_code,
                            buy_at - timedelta(minutes=1),
                            buy_at + timedelta(minutes=1),
                        )
                        if candle_at_buy:
                            close_price = float(candle_at_buy[0].close)
                            if close_price > 0:
                                llm_price_accuracy = (
                                    1 - abs(float(llm_price) - close_price) / close_price
                                ) * 100

        # 가상 슬리피지 (진입 속도 보완 ⑤)
        estimated_slippage: float | None = None
        if buy_at:
            ob_stmt = (
                select(OrderbookSnapshot)
                .where(
                    and_(
                        OrderbookSnapshot.stock_code == sell.stock_code,
                        OrderbookSnapshot.snapshot_at >= buy_at - timedelta(seconds=30),
                        OrderbookSnapshot.snapshot_at <= buy_at + timedelta(seconds=30),
                    )
                )
                .order_by(
                    sa_func.abs(
                        sa_func.extract("epoch", OrderbookSnapshot.snapshot_at)
                        - sa_func.extract("epoch", sa_func.cast(buy_at, OrderbookSnapshot.snapshot_at.type))
                    )
                )
                .limit(1)
            )
            try:
                ob_result = await db.execute(ob_stmt)
                ob = ob_result.scalar_one_or_none()
                if ob:
                    mid_price = (ob.ask_price1 + ob.bid_price1) / 2
                    if mid_price > 0:
                        spread = (ob.ask_price1 - ob.bid_price1) / 2
                        estimated_slippage = spread / mid_price * 100
            except Exception:
                pass

        verdict = _quality_verdict(capture_rate, grade, hold_mdd)

        items.append(
            MissedOpportunityItem(
                sell_order_id=sell.id,
                stock_code=sell.stock_code,
                stock_name=sell.stock_name,
                buy_price=buy_price,
                sell_price=sell_price,
                peak_price=peak_price,
                trough_price=trough_price,
                capture_rate=capture_rate,
                capture_grade=grade,
                hold_mdd=hold_mdd,
                trough_avoidance_rate=trough_avoidance,
                early_exit=early_exit,
                early_exit_upside=early_exit_upside,
                quality_verdict=verdict,
                llm_price_accuracy=llm_price_accuracy,
                estimated_slippage=estimated_slippage,
                holding_seconds=holding_seconds,
            )
        )

    return items


# ── #3: 시간대별 수익 분석 ──────────────────────────────────────


async def analyze_by_time_zone(
    db: AsyncSession, target_date: date
) -> tuple[list[TimeZoneStats], InactiveZoneStats | None]:
    start, end = _date_range(target_date)

    # SELL 주문 조회
    stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
                OrderHistory.profit_loss_net.is_not(None),
            )
        )
        .order_by(OrderHistory.result_executed_at.asc())
    )
    result = await db.execute(stmt)
    sells = list(result.scalars().all())

    # 6구간 그룹핑
    zone_data: dict[str, list[float]] = {}
    for name, _, _ in _TIME_ZONES:
        zone_data[name] = []

    for sell in sells:
        if sell.result_executed_at:
            zone = _classify_time_zone(sell.result_executed_at)
            if zone in zone_data:
                zone_data[zone].append(float(sell.profit_loss_net))

    zone_stats: list[TimeZoneStats] = []
    for name, _, _ in _TIME_ZONES:
        pnl_list = zone_data[name]
        count = len(pnl_list)
        if count == 0:
            zone_stats.append(TimeZoneStats(zone_name=name))
            continue

        wins = sum(1 for p in pnl_list if p >= 0)
        win_rate = (wins / count) * 100
        total_pnl = sum(pnl_list)
        ev = total_pnl / count

        warnings: list[str] = []
        if name == "점심" and count >= 3:
            warnings.append("점심시간 매매 3건 이상")
        if ev < 0:
            warnings.append(f"{name} 기대값 음수")

        zone_stats.append(
            TimeZoneStats(
                zone_name=name,
                trade_count=count,
                win_rate=win_rate,
                total_pnl=total_pnl,
                expected_value=ev,
                warnings=warnings,
            )
        )

    # 비활성 구간(09:00~09:11) 분석
    inactive_stats: InactiveZoneStats | None = None
    targets = await _get_active_target_stocks(db)
    if targets:
        inactive_start = datetime(
            target_date.year, target_date.month, target_date.day, 9, 0, 0
        )
        inactive_end = datetime(
            target_date.year, target_date.month, target_date.day, 9, 11, 0
        )

        stock_details: list[InactiveZoneStockDetail] = []
        for t in targets:
            candles = await _get_candles_in_range(
                db, t.stock_code, inactive_start, inactive_end
            )
            if not candles:
                continue

            high = float(max(c.high for c in candles))
            low = float(min(c.low for c in candles))
            open_price = float(candles[0].open)
            close_price = float(candles[-1].close)
            vol_sum = sum(c.volume for c in candles)

            price_range: float | None = None
            if open_price > 0:
                price_range = (high - low) / open_price * 100

            gap_retention: float | None = None
            if open_price > 0:
                gap_retention = close_price / open_price

            stock_details.append(
                InactiveZoneStockDetail(
                    stock_code=t.stock_code,
                    stock_name=t.stock_name,
                    price_range=price_range,
                    volume_sum=vol_sum,
                    gap_retention_rate=gap_retention,
                )
            )

        if stock_details:
            inactive_stats = InactiveZoneStats(stocks=stock_details)

    return zone_stats, inactive_stats


# ── #4: HOLD 판단 복기 ──────────────────────────────────────────


async def analyze_hold_review_41(
    db: AsyncSession, target_date: date
) -> list[HoldReviewItem_41]:
    """봤는데 안 산 것."""
    start, end = _date_range(target_date)

    # 보유 구간 구축 (BUY-SELL 페어)
    pairs = await _get_buy_sell_pairs(db, target_date)
    holding_periods: dict[str, list[tuple[datetime, datetime]]] = {}
    for sell, buy in pairs:
        if buy.result_executed_at and sell.result_executed_at:
            holding_periods.setdefault(sell.stock_code, []).append(
                (buy.result_executed_at, sell.result_executed_at)
            )

    # HOLD 판단 조회
    stmt = (
        select(DecisionHistory)
        .where(
            and_(
                DecisionHistory.decision == "HOLD",
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
        .order_by(DecisionHistory.created_at.asc())
    )
    result = await db.execute(stmt)
    holds = list(result.scalars().all())

    # 포지션 없는 HOLD만 필터
    def _is_no_position(stock_code: str, at: datetime) -> bool:
        periods = holding_periods.get(stock_code, [])
        for buy_at, sell_at in periods:
            if buy_at <= at <= sell_at:
                return False
        return True

    filtered_holds: list[DecisionHistory] = []
    for h in holds:
        if _is_no_position(h.stock_code, h.created_at):
            filtered_holds.append(h)

    # 연속 HOLD 묶기
    groups: list[list[DecisionHistory]] = []
    for h in filtered_holds:
        if groups and groups[-1][-1].stock_code == h.stock_code:
            last_time = groups[-1][-1].created_at
            # 30분 이내면 같은 관망 구간
            if (h.created_at - last_time).total_seconds() <= 1800:
                groups[-1].append(h)
                continue
        groups.append([h])

    items: list[HoldReviewItem_41] = []
    for group in groups:
        stock_code = group[0].stock_code
        stock_name = group[0].stock_name
        hold_start = group[0].created_at
        hold_end = group[-1].created_at

        # 당일 종가 기준 변동
        day_candles = await _get_candles_for_stock_date(
            db, stock_code, target_date
        )
        eod_change: float | None = None
        verdict: str | None = None
        if day_candles:
            first_close = float(day_candles[0].open)
            last_close = float(day_candles[-1].close)
            if first_close > 0:
                eod_change = (last_close - first_close) / first_close * 100

                if eod_change > 1.0:
                    verdict = "MISSED_UP"
                elif eod_change < -1.0:
                    verdict = "AVOIDED_DROP"
                else:
                    verdict = "CORRECT_HOLD"

        items.append(
            HoldReviewItem_41(
                stock_code=stock_code,
                stock_name=stock_name,
                hold_start=hold_start,
                hold_end=hold_end,
                hold_count=len(group),
                eod_change_rate=eod_change,
                verdict=verdict,
            )
        )

    return items


async def analyze_hold_review_42(
    db: AsyncSession, target_date: date
) -> list[HoldReviewItem_42]:
    """보지도 못한 것."""
    pairs = await _get_buy_sell_pairs(db, target_date)
    targets = await _get_active_target_stocks(db)
    target_codes = {t.stock_code: t.stock_name for t in targets}

    items: list[HoldReviewItem_42] = []
    for sell, buy in pairs:
        if not buy.result_executed_at or not sell.result_executed_at:
            continue

        hold_start = buy.result_executed_at
        hold_end = sell.result_executed_at

        # 보유 종목 이외의 감시 종목 검사
        for code, name in target_codes.items():
            if code == sell.stock_code:
                continue

            candles = await _get_candles_in_range(
                db, code, hold_start, hold_end
            )
            if not candles:
                continue

            open_p = float(candles[0].open)
            close_p = float(candles[-1].close)
            if open_p > 0:
                ret = (close_p - open_p) / open_p * 100
                items.append(
                    HoldReviewItem_42(
                        held_stock_code=sell.stock_code,
                        held_stock_name=sell.stock_name,
                        hold_start=hold_start,
                        hold_end=hold_end,
                        missed_stock_code=code,
                        missed_stock_name=name,
                        missed_return_rate=ret,
                    )
                )

    return items


async def get_hold_summary(
    db: AsyncSession, target_date: date
) -> HoldReviewSummary:
    start, end = _date_range(target_date)

    hold_41 = await analyze_hold_review_41(db, target_date)
    hold_42 = await analyze_hold_review_42(db, target_date)

    # 전체 판단 수 조회
    total_stmt = (
        select(sa_func.count(DecisionHistory.id))
        .where(
            and_(
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    total_result = await db.execute(total_stmt)
    total_decisions = total_result.scalar() or 0

    hold_stmt = (
        select(sa_func.count(DecisionHistory.id))
        .where(
            and_(
                DecisionHistory.decision == "HOLD",
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    hold_result = await db.execute(hold_stmt)
    hold_count = hold_result.scalar() or 0

    hold_ratio: float | None = None
    if total_decisions > 0:
        hold_ratio = (hold_count / total_decisions) * 100

    # Precision: BUY 판단 중 실제 상승 비율
    buy_stmt = (
        select(DecisionHistory)
        .where(
            and_(
                DecisionHistory.decision == "BUY",
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    buy_result = await db.execute(buy_stmt)
    buy_decisions = list(buy_result.scalars().all())

    precision: float | None = None
    if buy_decisions:
        rise_count = 0
        for bd in buy_decisions:
            day_candles = await _get_candles_for_stock_date(
                db, bd.stock_code, target_date
            )
            if day_candles:
                first_open = float(day_candles[0].open)
                last_close = float(day_candles[-1].close)
                if last_close > first_open:
                    rise_count += 1
        precision = (rise_count / len(buy_decisions)) * 100

    # Recall: 상승한 종목 중 BUY한 비율
    recall: float | None = None
    targets = await _get_active_target_stocks(db)
    if targets:
        rising_stocks: set[str] = set()
        bought_rising: set[str] = set()
        bought_codes = {bd.stock_code for bd in buy_decisions}

        for t in targets:
            day_candles = await _get_candles_for_stock_date(
                db, t.stock_code, target_date
            )
            if day_candles:
                first_open = float(day_candles[0].open)
                last_close = float(day_candles[-1].close)
                if last_close > first_open:
                    rising_stocks.add(t.stock_code)
                    if t.stock_code in bought_codes:
                        bought_rising.add(t.stock_code)

        if rising_stocks:
            recall = (len(bought_rising) / len(rising_stocks)) * 100

    return HoldReviewSummary(
        hold_41=hold_41,
        hold_42=hold_42,
        total_decisions=total_decisions,
        hold_count=hold_count,
        hold_ratio=hold_ratio,
        precision=precision,
        recall=recall,
    )


# ── #6: 변동성 대비 성과 ────────────────────────────────────────


async def analyze_volatility_capture(
    db: AsyncSession, target_date: date
) -> list[VolatilityCaptureItem]:
    pairs = await _get_buy_sell_pairs(db, target_date)
    if not pairs:
        return []

    items: list[VolatilityCaptureItem] = []
    for sell, buy in pairs:
        buy_price = float(buy.result_price)
        sell_price = float(sell.result_price)
        realized_pnl = sell_price - buy_price

        day_candles = await _get_candles_for_stock_date(
            db, sell.stock_code, target_date
        )
        if not day_candles:
            items.append(
                VolatilityCaptureItem(
                    stock_code=sell.stock_code,
                    stock_name=sell.stock_name,
                )
            )
            continue

        day_high = float(max(c.high for c in day_candles))
        day_low = float(min(c.low for c in day_candles))
        volatility = day_high - day_low

        capture_rate: float | None = None
        if volatility > 0:
            capture_rate = abs(realized_pnl) / volatility * 100

        # ATR(14분봉)
        atr_capture: float | None = None
        if len(day_candles) >= 2:
            true_ranges: list[float] = []
            for i, c in enumerate(day_candles):
                if i == 0:
                    tr = float(c.high - c.low)
                else:
                    prev_close = float(day_candles[i - 1].close)
                    tr = max(
                        float(c.high - c.low),
                        abs(float(c.high) - prev_close),
                        abs(float(c.low) - prev_close),
                    )
                true_ranges.append(tr)

            atr_period = min(14, len(true_ranges))
            atr = sum(true_ranges[:atr_period]) / atr_period
            if atr > 0:
                atr_capture = abs(realized_pnl) / atr

        # 변동폭 구간 분류
        open_price = float(day_candles[0].open)
        vol_pct = (volatility / open_price * 100) if open_price > 0 else 0
        if vol_pct < 1:
            vol_band = "저"
        elif vol_pct <= 3:
            vol_band = "중"
        else:
            vol_band = "고"

        # 시간 효율비
        time_eff: float | None = None
        if buy.result_executed_at and sell.result_executed_at:
            hold_minutes = (
                sell.result_executed_at - buy.result_executed_at
            ).total_seconds() / 60
            if hold_minutes > 0:
                time_eff = realized_pnl / hold_minutes

        items.append(
            VolatilityCaptureItem(
                stock_code=sell.stock_code,
                stock_name=sell.stock_name,
                capture_rate=capture_rate,
                atr_capture_rate=atr_capture,
                volatility_band=vol_band,
                time_efficiency=time_eff,
            )
        )

    return items


# ── #8: 벤치마크 대비 수익률 ────────────────────────────────────


async def analyze_benchmark(
    db: AsyncSession, target_date: date
) -> BenchmarkComparison:
    start, end = _date_range(target_date)

    # 시스템 수익률
    stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
                OrderHistory.profit_loss_net.is_not(None),
            )
        )
    )
    result = await db.execute(stmt)
    sells = list(result.scalars().all())

    total_pnl = sum(float(s.profit_loss_net) for s in sells)
    total_cost = sum(
        float(s.result_price) * s.result_quantity for s in sells
    )
    system_return = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    # 1차 벤치마크 (감시종목 평균)
    targets = await _get_active_target_stocks(db)
    stock_returns: list[dict] = []
    watchlist_returns: list[float] = []

    for t in targets:
        day_candles = await _get_candles_for_stock_date(
            db, t.stock_code, target_date
        )
        if not day_candles:
            continue
        open_p = float(day_candles[0].open)
        close_p = float(day_candles[-1].close)
        if open_p > 0:
            ret = (close_p - open_p) / open_p * 100
            watchlist_returns.append(ret)
            stock_returns.append(
                {
                    "stock_code": t.stock_code,
                    "stock_name": t.stock_name,
                    "return": ret,
                    "alpha": system_return - ret,
                }
            )

    watchlist_avg: float | None = None
    alpha_vs_watchlist: float | None = None
    if watchlist_returns:
        watchlist_avg = sum(watchlist_returns) / len(watchlist_returns)
        alpha_vs_watchlist = system_return - watchlist_avg

    # 2차 벤치마크 (코스피) — API 호출 실패 시 None 처리
    kospi_return: float | None = None
    alpha_vs_kospi: float | None = None
    market_condition: str | None = None

    try:
        from shared.kis import get_kospi_daily_return

        kospi_return = await get_kospi_daily_return(target_date)
        if kospi_return is not None:
            alpha_vs_kospi = system_return - kospi_return
            if kospi_return > 1:
                market_condition = "상승"
            elif kospi_return < -1:
                market_condition = "하락"
            else:
                market_condition = "횡보"
    except Exception:
        pass

    return BenchmarkComparison(
        watchlist_avg_return=watchlist_avg,
        kospi_return=kospi_return,
        alpha_vs_watchlist=alpha_vs_watchlist,
        alpha_vs_kospi=alpha_vs_kospi,
        per_stock_alpha=stock_returns if stock_returns else None,
        market_condition=market_condition,
    )


# ── #9: 동일종목 반복매매 ───────────────────────────────────────


async def analyze_repeated_trades(
    db: AsyncSession, target_date: date
) -> list[RepeatedTradeItem]:
    pairs = await _get_buy_sell_pairs(db, target_date)
    if not pairs:
        return []

    # 종목별 그룹핑
    by_stock: dict[str, list[tuple[OrderHistory, OrderHistory]]] = {}
    for sell, buy in pairs:
        by_stock.setdefault(sell.stock_code, []).append((sell, buy))

    items: list[RepeatedTradeItem] = []
    for code, trades in by_stock.items():
        if len(trades) < 2:
            continue

        per_round_returns: list[float] = []
        cumulative_fee = 0.0
        stock_name = trades[0][0].stock_name

        for sell, buy in trades:
            buy_price = float(buy.result_price)
            sell_price = float(sell.result_price)
            if buy_price > 0:
                ret = (sell_price - buy_price) / buy_price * 100
                per_round_returns.append(ret)

            # 수수료 = profit_loss - profit_loss_net
            if sell.profit_loss is not None and sell.profit_loss_net is not None:
                fee = float(sell.profit_loss) - float(sell.profit_loss_net)
                cumulative_fee += fee

        # 경고: 3회+ & 수익 감소 패턴
        warning = False
        warning_reason: str | None = None
        if len(per_round_returns) >= 3:
            decreasing = all(
                per_round_returns[i] >= per_round_returns[i + 1]
                for i in range(len(per_round_returns) - 1)
            )
            if decreasing:
                warning = True
                warning_reason = "3회 이상 반복매매 + 수익 감소 패턴"

        items.append(
            RepeatedTradeItem(
                stock_code=code,
                stock_name=stock_name,
                round_count=len(trades),
                per_round_returns=per_round_returns,
                cumulative_fee=cumulative_fee,
                warning=warning,
                warning_reason=warning_reason,
            )
        )

    return items


# ── #12: 매매 빈도 적정성 ───────────────────────────────────────


async def analyze_trade_frequency(
    db: AsyncSession, target_date: date
) -> TradeFrequencyStats:
    start, end = _date_range(target_date)

    # 전체 판단 건수
    total_stmt = (
        select(sa_func.count(DecisionHistory.id))
        .where(
            and_(
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    total_result = await db.execute(total_stmt)
    total_decisions = total_result.scalar() or 0

    # BUY 판단 건수
    buy_dec_stmt = (
        select(sa_func.count(DecisionHistory.id))
        .where(
            and_(
                DecisionHistory.decision == "BUY",
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    buy_dec_result = await db.execute(buy_dec_stmt)
    buy_decisions = buy_dec_result.scalar() or 0

    # BUY 실행 건수
    buy_exec_stmt = (
        select(sa_func.count(OrderHistory.id))
        .where(
            and_(
                OrderHistory.order_type == "BUY",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
            )
        )
    )
    buy_exec_result = await db.execute(buy_exec_stmt)
    buy_executions = buy_exec_result.scalar() or 0

    execution_rate: float | None = None
    if buy_decisions > 0:
        execution_rate = (buy_executions / buy_decisions) * 100

    # HOLD 비율
    hold_stmt = (
        select(sa_func.count(DecisionHistory.id))
        .where(
            and_(
                DecisionHistory.decision == "HOLD",
                DecisionHistory.created_at >= start,
                DecisionHistory.created_at < end,
            )
        )
    )
    hold_result = await db.execute(hold_stmt)
    hold_count = hold_result.scalar() or 0
    hold_ratio: float | None = None
    if total_decisions > 0:
        hold_ratio = (hold_count / total_decisions) * 100

    # 시간당 매매
    sell_stmt = (
        select(OrderHistory)
        .where(
            and_(
                OrderHistory.order_type == "SELL",
                OrderHistory.result_executed_at >= start,
                OrderHistory.result_executed_at < end,
            )
        )
    )
    sell_result = await db.execute(sell_stmt)
    sells = list(sell_result.scalars().all())
    total_trades = len(sells)

    # 장중 시간: 09:11~15:30 = 6시간 19분 = 379분
    market_minutes = 379.0
    trades_per_hour = (total_trades / (market_minutes / 60)) if total_trades > 0 else 0.0

    # 현금 유휴 시간: 장중 포지션 미보유 시간 비율
    pairs = await _get_buy_sell_pairs(db, target_date)
    held_minutes = 0.0
    for sell, buy in pairs:
        if buy.result_executed_at and sell.result_executed_at:
            held_minutes += (
                sell.result_executed_at - buy.result_executed_at
            ).total_seconds() / 60

    cash_idle_ratio: float | None = None
    if market_minutes > 0:
        cash_idle_ratio = ((market_minutes - held_minutes) / market_minutes) * 100
        cash_idle_ratio = max(0.0, min(100.0, cash_idle_ratio))

    # 수수료 비중
    total_fee = 0.0
    total_net_profit = 0.0
    for s in sells:
        if s.profit_loss is not None and s.profit_loss_net is not None:
            total_fee += float(s.profit_loss) - float(s.profit_loss_net)
            total_net_profit += float(s.profit_loss_net)

    fee_ratio: float | None = None
    fee_grade: str | None = None
    if total_net_profit > 0:
        fee_ratio = (total_fee / total_net_profit) * 100
        if fee_ratio < 10:
            fee_grade = "양호"
        elif fee_ratio < 20:
            fee_grade = "주의"
        elif fee_ratio < 30:
            fee_grade = "경고"
        else:
            fee_grade = "위험"
    elif total_fee > 0:
        fee_grade = "위험"

    return TradeFrequencyStats(
        total_decisions=total_decisions,
        buy_decisions=buy_decisions,
        buy_executions=buy_executions,
        execution_rate=execution_rate,
        hold_ratio=hold_ratio,
        trades_per_hour=trades_per_hour,
        cash_idle_ratio=cash_idle_ratio,
        fee_ratio=fee_ratio,
        fee_grade=fee_grade,
    )


# ── #13: 매수가 최적성 ─────────────────────────────────────────


async def analyze_entry_quality(
    db: AsyncSession, target_date: date
) -> list[EntryQualityItem]:
    pairs = await _get_buy_sell_pairs(db, target_date)
    if not pairs:
        return []

    items: list[EntryQualityItem] = []
    for sell, buy in pairs:
        buy_price = float(buy.result_price)
        buy_at = buy.result_executed_at

        day_candles = await _get_candles_for_stock_date(
            db, sell.stock_code, target_date
        )
        if not day_candles:
            items.append(
                EntryQualityItem(
                    stock_code=sell.stock_code,
                    stock_name=sell.stock_name,
                    buy_price=buy_price,
                )
            )
            continue

        day_high = float(max(c.high for c in day_candles))
        day_low = float(min(c.low for c in day_candles))

        entry_position: float | None = None
        if day_high != day_low:
            entry_position = (buy_price - day_low) / (day_high - day_low) * 100

        # 매수 후 추가 하락
        additional_drop: float | None = None
        if buy_at:
            post_candles = [
                c for c in day_candles if c.minute_at >= buy_at
            ]
            if post_candles:
                post_low = float(min(c.low for c in post_candles))
                additional_drop = post_low - buy_price

        items.append(
            EntryQualityItem(
                stock_code=sell.stock_code,
                stock_name=sell.stock_name,
                buy_price=buy_price,
                day_low=day_low,
                day_high=day_high,
                entry_position_pct=entry_position,
                additional_drop=additional_drop,
            )
        )

    return items
