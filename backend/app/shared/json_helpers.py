"""LLM 응답 JSON 파싱 및 트레이딩 판단 정규화."""

from __future__ import annotations

import json
from typing import Any


def parse_llm_json_object(raw_text: str) -> dict:
    """LLM 응답 텍스트에서 JSON 객체를 추출하여 dict로 반환한다."""
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("빈 응답입니다")

    json_start = text.find("{")
    if json_start > 0:
        text = text[json_start:]

    try:
        payload = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        raise ValueError("JSON 파싱 실패") from exc

    if not isinstance(payload, dict):
        raise ValueError("JSON object(dict)만 허용됩니다")
    return payload


def normalize_trade_decision(payload: dict) -> dict:
    """파싱된 LLM 응답에서 decision을 정규화한다.

    BUY/SELL일 때 quantity/price가 유효하지 않으면 HOLD로 다운그레이드한다.
    """
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("decision 키가 필요합니다")

    raw_result = decision.get("result")
    result = str(raw_result).strip().upper() if isinstance(raw_result, str) else "HOLD"
    if result not in {"BUY", "SELL", "HOLD"}:
        result = "HOLD"

    quantity = _coerce_number(decision.get("quantity", decision.get("수량")))
    price = _coerce_number(decision.get("price", decision.get("가격")))

    if result in {"BUY", "SELL"} and (
        quantity is None or price is None or quantity <= 0 or price <= 0
    ):
        result = "HOLD"

    stock_code = decision.get("stock_code", decision.get("종목코드"))
    normalized = dict(payload)
    normalized["decision"] = {
        **decision,
        "result": result,
        "stock_code": stock_code,
        "quantity": quantity,
        "price": price,
    }
    return normalized


def _coerce_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped) if "." in stripped else int(stripped)
        except ValueError:
            return None
    return None
