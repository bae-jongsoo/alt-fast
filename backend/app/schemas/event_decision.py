"""이벤트 기반 매매 판단 LLM 응답 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class EventDecisionResponse(BaseModel):
    decision: Literal["BUY", "HOLD"]  # 이벤트 기반이므로 SELL 없음 (청산은 별도)
    confidence: float  # 0.0 ~ 1.0
    reasoning: str  # 판단 근거
    target_return_pct: float | None = None  # 목표 수익률 (예: 3.0 → 3%)
    stop_pct: float | None = None  # 손절 수준 (예: -2.0 → -2%)
    holding_days: int | None = None  # 예상 보유 기간 (일)
    event_assessment: str = ""  # 이벤트에 대한 평가
    risk_factors: list[str] = []  # 리스크 요인
