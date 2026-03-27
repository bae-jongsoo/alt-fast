"""보고서 서비스 Pydantic 응답 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EntrySpeedBreakdown(BaseModel):
    """진입 속도 3구간 분해."""

    llm_processing_ms: int | None = Field(None, description="LLM 처리 시간 (ms)")
    decision_to_order_ms: float | None = Field(
        None, description="판단→주문 시간 (ms)"
    )
    order_to_execution_ms: float | None = Field(
        None, description="주문→체결 시간 (ms)"
    )


class TradeTimelineItem(BaseModel):
    """개별 매매 기록."""

    sell_order_id: int
    buy_order_id: int | None = None
    stock_code: str
    stock_name: str
    buy_price: float
    sell_price: float
    quantity: int
    buy_executed_at: datetime | None = None
    sell_executed_at: datetime | None = None
    holding_seconds: float | None = Field(None, description="보유시간 (초)")
    holding_category: str | None = Field(
        None, description="초단타/단타/스윙단타/중기"
    )
    time_zone_tag: str | None = Field(
        None, description="장초반/오전장/점심/오후장/마감접근/동시호가"
    )
    profit_loss_net: float | None = Field(None, description="세후 손익")
    entry_speed: EntrySpeedBreakdown | None = None
    is_simulated: bool = True


class WinLossStats(BaseModel):
    """승률/손익비/기대값 통계."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = Field(0.0, description="승률 (%)")
    avg_profit: float = Field(0.0, description="평균 이익 (세후)")
    avg_loss: float = Field(0.0, description="평균 손실 (세후)")
    profit_loss_ratio: float | None = Field(None, description="손익비")
    expected_value: float = Field(0.0, description="기대값")
    profit_factor: float | None = Field(None, description="Profit Factor")
    effective_profit_loss_ratio: float | None = Field(
        None, description="실질 손익비 (세후 기준)"
    )
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    is_simulated: bool = True


class TradeWaterfallItem(BaseModel):
    """거래별 손익 워터폴."""

    trade_number: int
    stock_name: str
    stock_code: str
    profit_loss_net: float
    cumulative_profit_loss: float
    executed_at: datetime | None = None
    is_simulated: bool = True


class DailyReportSummary(BaseModel):
    """Level 1 Executive Summary."""

    date: str
    net_profit_loss: float = Field(0.0, description="당일 순손익 (세후)")
    return_rate: float | None = Field(None, description="수익률 (%)")
    total_trades: int = 0
    win_rate: float = Field(0.0, description="승률 (%)")
    expected_value: float = Field(0.0, description="기대값")
    profit_factor: float | None = None
    intraday_mdd: float | None = Field(None, description="일중 MDD")
    mdd_recovery_seconds: float | None = Field(None, description="MDD 회복 시간 (초)")
    starting_cash: float | None = Field(None, description="시작 현금")
    is_simulated: bool = True


# ── Task 02: 분석 항목 스키마 ────────────────────────────────────


class MissedOpportunityItem(BaseModel):
    """놓친 기회 분석 항목."""

    sell_order_id: int
    stock_code: str
    stock_name: str
    buy_price: float
    sell_price: float
    peak_price: float | None = Field(None, description="보유 중 최고가")
    trough_price: float | None = Field(None, description="보유 중 최저가")
    capture_rate: float | None = Field(None, description="고점 캡처율 (%)")
    capture_grade: str | None = Field(
        None, description="우수/보통/미흡 (보유시간별 동적 기준)"
    )
    hold_mdd: float | None = Field(None, description="보유 중 MDD (%)")
    trough_avoidance_rate: float | None = Field(None, description="저점 회피율")
    early_exit: bool = Field(False, description="조기 청산 여부")
    early_exit_upside: float | None = Field(
        None, description="매도 후 10분 내 상승폭 (%)"
    )
    quality_verdict: str | None = Field(None, description="매매 품질 종합 판정")
    llm_price_accuracy: float | None = Field(
        None, description="LLM 가격 정확도 (%)"
    )
    estimated_slippage: float | None = Field(
        None, description="가상 슬리피지 (%)"
    )
    holding_seconds: float | None = None


class TimeZoneStats(BaseModel):
    """시간대별 수익 통계."""

    zone_name: str = Field(..., description="시간대 구간명")
    trade_count: int = 0
    win_rate: float = Field(0.0, description="승률 (%)")
    total_pnl: float = Field(0.0, description="총 손익")
    expected_value: float = Field(0.0, description="기대값")
    warnings: list[str] = Field(default_factory=list)


class InactiveZoneStockDetail(BaseModel):
    """비활성 구간 종목별 상세."""

    stock_code: str
    stock_name: str | None = None
    price_range: float | None = Field(None, description="변동폭 (%)")
    volume_sum: int | None = Field(None, description="거래량 합계")
    gap_retention_rate: float | None = Field(None, description="갭 유지율")


class InactiveZoneStats(BaseModel):
    """비활성 구간(09:00~09:11) 분석."""

    stocks: list[InactiveZoneStockDetail] = Field(default_factory=list)
    note: str = "09:00~09:11 비활성 구간 감시종목 변동 분석 (가상 시뮬레이션)"


class HoldReviewItem_41(BaseModel):
    """봤는데 안 산 것."""

    stock_code: str
    stock_name: str | None = None
    hold_start: datetime | None = None
    hold_end: datetime | None = None
    hold_count: int = Field(0, description="연속 HOLD 횟수")
    eod_change_rate: float | None = Field(None, description="당일종가 기준 변동 (%)")
    verdict: str | None = Field(
        None, description="MISSED_UP / CORRECT_HOLD / AVOIDED_DROP"
    )


class HoldReviewItem_42(BaseModel):
    """보지도 못한 것."""

    held_stock_code: str
    held_stock_name: str | None = None
    hold_start: datetime | None = None
    hold_end: datetime | None = None
    missed_stock_code: str
    missed_stock_name: str | None = None
    missed_return_rate: float | None = Field(
        None, description="미평가 종목 해당 구간 수익률 (%)"
    )


class HoldReviewSummary(BaseModel):
    """HOLD 복기 요약."""

    hold_41: list[HoldReviewItem_41] = Field(default_factory=list)
    hold_42: list[HoldReviewItem_42] = Field(default_factory=list)
    total_decisions: int = 0
    hold_count: int = 0
    hold_ratio: float | None = Field(None, description="HOLD 비율 (%)")
    precision: float | None = Field(None, description="BUY 판단 중 실제 상승 비율")
    recall: float | None = Field(None, description="상승한 것 중 BUY한 비율")


class VolatilityCaptureItem(BaseModel):
    """변동성 대비 성과."""

    stock_code: str
    stock_name: str | None = None
    capture_rate: float | None = Field(None, description="캡처율 (%)")
    atr_capture_rate: float | None = Field(None, description="ATR 캡처율")
    volatility_band: str | None = Field(None, description="저/중/고")
    time_efficiency: float | None = Field(
        None, description="시간 효율비 (원/분)"
    )


class BenchmarkComparison(BaseModel):
    """벤치마크 대비 수익률."""

    watchlist_avg_return: float | None = Field(
        None, description="감시종목 평균 등락률 (%)"
    )
    kospi_return: float | None = Field(None, description="코스피 등락률 (%)")
    alpha_vs_watchlist: float | None = Field(None, description="1차 Alpha (%)")
    alpha_vs_kospi: float | None = Field(None, description="2차 Alpha (%)")
    per_stock_alpha: list[dict] | None = Field(
        None, description="종목별 Alpha"
    )
    market_condition: str | None = Field(
        None, description="상승/횡보/하락"
    )


class RepeatedTradeItem(BaseModel):
    """동일종목 반복매매."""

    stock_code: str
    stock_name: str | None = None
    round_count: int = Field(0, description="회차")
    per_round_returns: list[float] = Field(
        default_factory=list, description="각 회차 수익률 (%)"
    )
    cumulative_fee: float = Field(0.0, description="수수료 누적")
    warning: bool = Field(False, description="경고 플래그")
    warning_reason: str | None = None


class TradeFrequencyStats(BaseModel):
    """매매 빈도 적정성."""

    total_decisions: int = 0
    buy_decisions: int = 0
    buy_executions: int = 0
    execution_rate: float | None = Field(None, description="실행률 (%)")
    hold_ratio: float | None = Field(None, description="HOLD 비율 (%)")
    trades_per_hour: float | None = Field(None, description="시간당 매매")
    cash_idle_ratio: float | None = Field(
        None, description="현금 유휴 시간 비율 (%)"
    )
    fee_ratio: float | None = Field(None, description="수수료 비중 (%)")
    fee_grade: str | None = Field(
        None, description="양호/주의/경고/위험"
    )


class EntryQualityItem(BaseModel):
    """매수가 최적성."""

    stock_code: str
    stock_name: str | None = None
    buy_price: float
    day_low: float | None = None
    day_high: float | None = None
    entry_position_pct: float | None = Field(
        None, description="매수 위치 (%)"
    )
    additional_drop: float | None = Field(
        None, description="매수 후 추가 하락폭"
    )


# ── Task 03: 고급 분석 스키마 ──────────────────────────────────────


class LLMSourceStats(BaseModel):
    """소스 type별 통계."""

    source_type: str = Field(..., description="소스 유형 (기술적분석/뉴스/공시/수급 등)")
    mention_count: int = Field(0, description="출현 횟수")
    win_rate_with: float = Field(0.0, description="해당 소스 언급 시 승률 (%)")
    win_rate_without: float = Field(0.0, description="해당 소스 미언급 시 승률 (%)")


class LLMSourceReview(BaseModel):
    """LLM 판단근거 복기 요약."""

    source_stats: list[LLMSourceStats] = Field(default_factory=list)
    best_source: str | None = Field(None, description="가장 적중률 높은 소스")
    worst_source: str | None = Field(None, description="가장 적중률 낮은 소스")
    total_buy_decisions: int = 0
    data_count: int = Field(0, description="분석에 사용된 판단 건수")


class OrderbookSignal(BaseModel):
    """호가 가공 지표."""

    supply_demand_ratio: float | None = Field(
        None, description="수급 비율 (bid/ask)"
    )
    spread_ratio: float | None = Field(None, description="스프레드 비율 (%)")
    bid1_concentration: float | None = Field(
        None, description="1호가 집중도"
    )
    sell_wall_exists: bool = Field(False, description="매도벽 존재 여부")
    supply_change_rate: float | None = Field(
        None, description="수급 변화율 (%)"
    )


class OrderbookAnalysis(BaseModel):
    """호가 활용도 검증."""

    supply_advantage_win_rate: float | None = Field(
        None, description="수급 우위 시 승률 (%)"
    )
    supply_disadvantage_win_rate: float | None = Field(
        None, description="수급 열위 시 승률 (%)"
    )
    wide_spread_avg_pnl: float | None = Field(
        None, description="스프레드 넓은 시점 평균 손익"
    )
    narrow_spread_avg_pnl: float | None = Field(
        None, description="스프레드 좁은 시점 평균 손익"
    )
    is_sufficient: bool = Field(True, description="데이터 충분 여부")
    message: str | None = None
    data_count: int = Field(0, description="분석에 사용된 호가 건수")
    signals: list[OrderbookSignal] = Field(default_factory=list)


class CumulativeStats(BaseModel):
    """누적 추적 지표."""

    cumulative_win_rate: float = Field(0.0, description="누적 승률 (%)")
    cumulative_expected_value: float = Field(0.0, description="누적 기대값")
    cumulative_profit_factor: float | None = Field(None, description="누적 PF")
    cumulative_mdd: float | None = Field(None, description="누적 MDD (최악일)")
    total_trades: int = Field(0, description="총 거래 수")
    ci_lower: float | None = Field(None, description="95% 신뢰구간 하한 (%)")
    ci_upper: float | None = Field(None, description="95% 신뢰구간 상한 (%)")
    strategy_version: str | None = Field(None, description="전략 버전")
    version_trade_count: int = Field(0, description="버전 내 거래 수")
    confidence_label: str | None = Field(None, description="통계적 신뢰도 라벨")


class RollingWindowStats(BaseModel):
    """개별 롤링 윈도우."""

    window_size: int
    win_rate: float | None = Field(None, description="롤링 승률 (%)")
    expected_value: float | None = Field(None, description="롤링 기대값")


class RollingStats(BaseModel):
    """롤링 윈도우 통계."""

    windows: list[RollingWindowStats] = Field(default_factory=list)


class VersionComparison(BaseModel):
    """전략 버전별 성과 비교."""

    version: str
    win_rate: float = Field(0.0, description="승률 (%)")
    expected_value: float = Field(0.0, description="기대값")
    profit_factor: float | None = Field(None, description="PF")
    trade_count: int = Field(0, description="거래 수")


class AlertItem(BaseModel):
    """경고 항목."""

    type: str = Field(..., description="INFO / WARNING / CRITICAL")
    category: str = Field(..., description="경고 카테고리 (time_zone/hold/strategy/fee 등)")
    message: str = Field(..., description="경고 메시지")
    action: str = Field(..., description="권고 액션")


class DailyReportResponse(BaseModel):
    """전체 보고서 응답."""

    summary: DailyReportSummary
    trades: list[TradeTimelineItem] = []
    waterfall: list[TradeWaterfallItem] = []
    win_loss_stats: WinLossStats | None = None
    analysis: dict | None = None
    cumulative: CumulativeStats | None = None
    rolling: RollingStats | None = None
    alerts: list[AlertItem] = Field(default_factory=list)
    is_simulated: bool = True
