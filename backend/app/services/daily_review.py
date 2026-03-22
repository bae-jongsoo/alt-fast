from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import async_session
from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory
from app.shared.llm import ask_llm_by_level, get_llm_level
from app.shared.telegram import send_message

KST = ZoneInfo("Asia/Seoul")


def _date_range_naive_kst(target: datetime) -> tuple[datetime, datetime]:
    """DB columns are timestamp without tz.

    We interpret stored values as KST for daily boundaries.
    """
    start = datetime(target.year, target.month, target.day, 0, 0, 0)
    end = start + timedelta(days=1)
    return start, end


def _safe_truncate(s: str | None, limit: int = 1200) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + "…"


def _to_kst_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST).isoformat()
    return dt.astimezone(KST).isoformat()


async def fetch_daily_bundle(target_date: datetime) -> dict:
    start, end = _date_range_naive_kst(target_date)

    async with async_session() as session:
        q = (
            select(OrderHistory)
            .where(
                (
                    (OrderHistory.result_executed_at.is_not(None))
                    & (OrderHistory.result_executed_at >= start)
                    & (OrderHistory.result_executed_at < end)
                )
                | (
                    (OrderHistory.order_placed_at >= start)
                    & (OrderHistory.order_placed_at < end)
                )
            )
            .order_by(OrderHistory.order_placed_at.asc())
        )
        orders = (await session.execute(q)).scalars().all()

        decision_ids = sorted({o.decision_history_id for o in orders if o.decision_history_id})
        decisions: list[DecisionHistory] = []
        if decision_ids:
            dq = (
                select(DecisionHistory)
                .where(DecisionHistory.id.in_(decision_ids))
                .order_by(DecisionHistory.created_at.asc())
            )
            decisions = (await session.execute(dq)).scalars().all()

    trades: list[dict] = []
    realized = 0.0
    sell_count = 0
    win_count = 0

    for o in orders:
        pnl = float(o.profit_loss) if o.profit_loss is not None else None
        if o.order_type == "SELL" and pnl is not None:
            realized += pnl
            sell_count += 1
            if pnl > 0:
                win_count += 1

        trades.append(
            {
                "order_id": o.id,
                "decision_history_id": o.decision_history_id,
                "stock_code": o.stock_code,
                "stock_name": o.stock_name,
                "order_type": o.order_type,
                "order_price": float(o.order_price),
                "order_qty": o.order_quantity,
                "result_price": float(o.result_price) if o.result_price is not None else None,
                "result_qty": o.result_quantity,
                "profit_loss": pnl,
                "profit_rate": float(o.profit_rate) if o.profit_rate is not None else None,
                "order_placed_at": _to_kst_iso(o.order_placed_at),
                "result_executed_at": _to_kst_iso(o.result_executed_at),
            }
        )

    win_rate = (win_count / sell_count) if sell_count else None

    decision_rows: list[dict] = []
    for d in decisions:
        decision_rows.append(
            {
                "decision_id": d.id,
                "stock_code": d.stock_code,
                "stock_name": d.stock_name,
                "decision": d.decision,
                "parsed_decision": d.parsed_decision,
                "is_error": d.is_error,
                "error_message": _safe_truncate(d.error_message, 300),
                "created_at": _to_kst_iso(d.created_at),
            }
        )

    return {
        "date": target_date.date().isoformat(),
        "tz": "Asia/Seoul",
        "summary": {
            "total_trades": len(trades),
            "buys": sum(1 for t in trades if t["order_type"] == "BUY"),
            "sells": sum(1 for t in trades if t["order_type"] == "SELL"),
            "realized_pnl_sum": realized if sell_count else None,
            "win_rate": win_rate,
        },
        "trades": trades,
        "decisions": decision_rows,
    }


def build_daily_review_prompt(bundle: dict) -> str:
    evidence = json.dumps(bundle, ensure_ascii=False)
    date = bundle.get("date")
    summary = bundle.get("summary")

    return f"""너는 한국 주식 자동매매 시스템의 '일일 회고 리뷰어'다.
규칙/체크리스트 나열 금지. 데이터에 근거해서만 말해라. 데이터에 없으면 UNKNOWN.

아래는 오늘({date}, KST) 로그다.
SUMMARY: {summary}
EVIDENCE_JSON:
{evidence}

아래 4개 섹션만, 각 섹션 최대 5줄.
[결론] 오늘 시스템이 어떤 식으로 돈을 벌었/잃었는지 1~2문장. 승률뿐 아니라 평균 이익/손실 비율도 언급.
[Best/Worst] Best 1 / Worst 1: order_id 명시, 진입/청산/깨진가정 1줄씩
[패턴] 오늘 드러난 판단 패턴 1개 + 근거 order_id 2개 이상. sources의 weight 분포에서 특정 소스에 과의존했다면 지적.
[내일 프롬프트 수정안] 오늘 패턴을 근거로, 매수 또는 매도 프롬프트에서 수정할 문장 1~2줄을 그대로 제시. 단, 구체적 수치(N분, N% 등)를 확정짓지 말고 조건의 방향성(어떤 조건을 추가/강화/완화할지)을 제시하라.
"""


async def generate_and_send_daily_review(target_date: datetime, dry_run: bool = False) -> str:
    bundle = await fetch_daily_bundle(target_date)
    prompt = build_daily_review_prompt(bundle)

    level = await get_llm_level("llm_review", "high")
    review_text = await ask_llm_by_level(level, prompt, timeout_seconds=120)
    if len(review_text) > 3500:
        review_text = review_text[:3500] + "\n…(truncated)"

    msg = f"[ALT 일일 회고] {bundle['date']}\n" + review_text

    if not dry_run:
        await send_message(msg)

    return msg
