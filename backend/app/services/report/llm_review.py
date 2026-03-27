"""보고서 LLM 리뷰 — 보고서 JSON을 LLM에 넘겨 종합 리뷰를 생성한다."""

from __future__ import annotations

import json
import logging

from app.schemas.report import DailyReportResponse

logger = logging.getLogger(__name__)


def _build_review_prompt(report: DailyReportResponse) -> str:
    """LLM 리뷰용 프롬프트를 구성한다."""
    report_dict = report.model_dump()

    summary_json = json.dumps(report_dict.get("summary", {}), ensure_ascii=False, default=str, indent=2)
    alerts_json = json.dumps(
        [a for a in report_dict.get("alerts", [])],
        ensure_ascii=False, default=str, indent=2,
    )
    cumulative_json = json.dumps(report_dict.get("cumulative") or {}, ensure_ascii=False, default=str, indent=2)

    prompt = f"""아래는 오늘의 자동매매 시스템 일일 보고서입니다.
숫자와 경고를 기반으로 종합적인 리뷰를 작성하세요.

[보고서 요약]
{summary_json}

[경고 사항]
{alerts_json}

[누적 지표]
{cumulative_json}

다음 관점에서 분석하세요:
1. 오늘 매매의 전반적 평가
2. 경고 사항에 대한 구체적 해석
3. 내일 매매에 반영할 사항 (1~2개)"""

    return prompt


async def generate_llm_review(report: DailyReportResponse) -> str:
    """보고서에 대한 LLM 종합 리뷰를 생성한다.

    LLM 호출 실패 시 빈 문자열을 반환 (보고서 자체에는 영향 없음).
    """
    try:
        from app.shared.llm import ask_llm

        prompt = _build_review_prompt(report)
        review = await ask_llm(prompt, timeout_seconds=90)
        return review
    except Exception:
        logger.exception("LLM 리뷰 생성 실패")
        return ""
