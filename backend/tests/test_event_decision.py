"""이벤트 기반 LLM 판단 서비스 테스트."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.macro_snapshot import MacroSnapshot
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.news import News
from app.models.orderbook_snapshot import OrderbookSnapshot
from app.models.prompt_template import PromptTemplate
from app.models.strategy import Strategy
from app.models.trading_event import TradingEvent
from app.schemas.event_decision import EventDecisionResponse
from app.services.event_decision import (
    build_event_prompt,
    make_event_decision,
    parse_event_decision,
)

KST = timezone(timedelta(hours=9))

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _now() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


async def _create_strategy(db: AsyncSession, name: str = "event_trader") -> Strategy:
    strategy = Strategy(
        name=f"{name}_{_now().timestamp()}",
        description="이벤트 트레이더 테스트",
        initial_capital=Decimal("10000000"),
        is_active=True,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_prompt_template(
    db: AsyncSession, strategy_id: int
) -> PromptTemplate:
    template = PromptTemplate(
        strategy_id=strategy_id,
        prompt_type="event_buy",
        content=(
            "당신은 이벤트 기반 트레이딩 전문가입니다.\n"
            "현재 시각: {{ current_time }}\n"
            "이벤트 유형: {{ event_type }}\n"
            "종목: {{ stock_name }} ({{ stock_code }})\n"
            "컨텍스트:\n{{ context_json }}\n"
            "위 정보를 분석하여 JSON으로 응답하세요."
        ),
        version=1,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


def _make_event(
    stock_code: str,
    stock_name: str,
    strategy_id: int | None = None,
    event_type: str = "volume_spike",
) -> TradingEvent:
    return TradingEvent(
        event_type=event_type,
        stock_code=stock_code,
        stock_name=stock_name,
        event_data={"spike_ratio": 3.0},
        confidence_hint=Decimal("0.70"),
        status="pending",
        strategy_id=strategy_id,
        detected_at=_now(),
    )


async def _setup_context_data(
    db: AsyncSession,
    stock_code: str,
    strategy_id: int,
) -> None:
    """프롬프트 빌드에 필요한 컨텍스트 데이터 생성."""
    now = _now()

    # MarketSnapshot
    db.add(MarketSnapshot(
        stock_code=stock_code,
        stock_name="테스트종목",
        external_id=f"ms_ed_{stock_code}_{now.timestamp()}",
        published_at=now,
        per=Decimal("15.5"),
        pbr=Decimal("1.2"),
        eps=Decimal("5000"),
        bps=Decimal("40000"),
        hts_avls=100000000000,
        w52_hgpr=70000,
        w52_lwpr=40000,
        hts_frgn_ehrt=Decimal("30.5"),
        vol_tnrt=Decimal("2.1"),
    ))

    # MacroSnapshot
    db.add(MacroSnapshot(
        snapshot_date=date.today(),
        sp500_close=Decimal("5200.50"),
        sp500_change_pct=Decimal("0.75"),
        nasdaq_close=Decimal("16500.30"),
        nasdaq_change_pct=Decimal("1.20"),
        vix=Decimal("15.5"),
        us_10y_treasury=Decimal("4.25"),
        usd_krw=Decimal("1350.50"),
        usd_krw_change_pct=Decimal("-0.30"),
    ))

    # News
    for i in range(3):
        db.add(News(
            stock_code=stock_code,
            stock_name="테스트종목",
            external_id=f"news_ed_{stock_code}_{i}_{now.timestamp()}",
            title=f"테스트 뉴스 {i}",
            summary=f"뉴스 요약 {i}",
            useful=True,
            published_at=now - timedelta(hours=i),
        ))

    # DartDisclosure
    db.add(DartDisclosure(
        stock_code=stock_code,
        stock_name="테스트종목",
        external_id=f"dart_ed_{stock_code}_{now.timestamp()}",
        corp_code="00126380",
        rcept_no="20260329000001",
        title="테스트 공시",
        description="공시 상세 내용",
        published_at=now - timedelta(hours=2),
    ))

    # MinuteCandle
    for i in range(10):
        db.add(MinuteCandle(
            stock_code=stock_code,
            minute_at=now - timedelta(minutes=10 - i),
            open=50000 + i * 100,
            high=50200 + i * 100,
            low=49800 + i * 100,
            close=50100 + i * 100,
            volume=1000 + i * 50,
        ))

    # OrderbookSnapshot
    db.add(OrderbookSnapshot(
        stock_code=stock_code,
        snapshot_at=now,
        ask_price1=50200, ask_price2=50300, ask_price3=50400,
        ask_price4=50500, ask_price5=50600,
        ask_volume1=100, ask_volume2=200, ask_volume3=300,
        ask_volume4=400, ask_volume5=500,
        bid_price1=50100, bid_price2=50000, bid_price3=49900,
        bid_price4=49800, bid_price5=49700,
        bid_volume1=100, bid_volume2=200, bid_volume3=300,
        bid_volume4=400, bid_volume5=500,
    ))

    # Cash asset
    db.add(Asset(
        strategy_id=strategy_id,
        stock_code=None,
        stock_name=None,
        quantity=1,
        unit_price=Decimal("0"),
        total_amount=Decimal("10000000"),
    ))

    await db.commit()


# ─── 프롬프트 빌드 테스트 ───


async def test_build_event_prompt_contains_context(db: AsyncSession):
    """프롬프트에 이벤트 + 매크로 + 뉴스 + 공시 + 분봉 + 호가 정보가 포함된다."""
    strategy = await _create_strategy(db)
    await _create_prompt_template(db, strategy.id)

    stock_code = "005930"
    await _setup_context_data(db, stock_code, strategy.id)

    event = _make_event(stock_code, "삼성전자", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    prompt = await build_event_prompt(db, event, strategy.id)

    # 이벤트 정보
    assert "volume_spike" in prompt
    assert "005930" in prompt
    assert "삼성전자" in prompt

    # 거시 데이터
    assert "sp500_close" in prompt
    assert "vix" in prompt
    assert "usd_krw" in prompt

    # 뉴스
    assert "테스트 뉴스" in prompt

    # 공시
    assert "테스트 공시" in prompt

    # 분봉
    assert "open" in prompt
    assert "close" in prompt
    assert "volume" in prompt

    # 호가
    assert "asks" in prompt
    assert "bids" in prompt

    # 포트폴리오
    assert "cash" in prompt

    # 템플릿 변수가 렌더링됨
    assert "{{ " not in prompt


# ─── LLM 응답 파싱 테스트 (정상) ───


async def test_parse_event_decision_normal():
    """정상 JSON 응답을 EventDecisionResponse로 파싱한다."""
    raw = """{
        "decision": "BUY",
        "confidence": 0.85,
        "reasoning": "강한 거래량 급증과 긍정적 뉴스",
        "target_return_pct": 3.0,
        "stop_pct": -2.0,
        "holding_days": 5,
        "event_assessment": "거래량 3배 급증은 기관 매집 신호",
        "risk_factors": ["환율 불안정", "VIX 상승"]
    }"""

    result = parse_event_decision(raw)

    assert isinstance(result, EventDecisionResponse)
    assert result.decision == "BUY"
    assert result.confidence == 0.85
    assert result.reasoning == "강한 거래량 급증과 긍정적 뉴스"
    assert result.target_return_pct == 3.0
    assert result.stop_pct == -2.0
    assert result.holding_days == 5
    assert result.event_assessment == "거래량 3배 급증은 기관 매집 신호"
    assert len(result.risk_factors) == 2
    assert "환율 불안정" in result.risk_factors


async def test_parse_event_decision_hold():
    """HOLD 판단도 정상 파싱된다."""
    raw = """{
        "decision": "HOLD",
        "confidence": 0.3,
        "reasoning": "불확실한 시장 상황",
        "event_assessment": "이벤트 신뢰도 낮음",
        "risk_factors": ["시장 변동성"]
    }"""

    result = parse_event_decision(raw)

    assert result.decision == "HOLD"
    assert result.confidence == 0.3
    assert result.target_return_pct is None
    assert result.stop_pct is None
    assert result.holding_days is None


# ─── 파싱 실패 시 기본값 테스트 ───


async def test_parse_event_decision_invalid_decision_defaults_to_hold():
    """decision이 BUY/HOLD가 아니면 HOLD로 기본값 적용."""
    raw = """{
        "decision": "SELL",
        "confidence": 0.9,
        "reasoning": "판매 판단"
    }"""

    result = parse_event_decision(raw)
    assert result.decision == "HOLD"


async def test_parse_event_decision_missing_fields():
    """필수 필드 누락 시 기본값 적용."""
    raw = """{"decision": "BUY"}"""

    result = parse_event_decision(raw)
    assert result.decision == "BUY"
    assert result.confidence == 0.0
    assert result.reasoning == ""
    assert result.target_return_pct is None
    assert result.stop_pct is None
    assert result.holding_days is None
    assert result.event_assessment == ""
    assert result.risk_factors == []


async def test_parse_event_decision_invalid_json():
    """JSON 파싱 실패 시 ValueError."""
    with pytest.raises(ValueError, match="JSON 파싱 실패|빈 응답"):
        parse_event_decision("이것은 JSON이 아닙니다")


async def test_parse_event_decision_confidence_clamped():
    """confidence가 범위를 벗어나면 0~1로 클램핑."""
    raw = """{
        "decision": "BUY",
        "confidence": 1.5,
        "reasoning": "test"
    }"""

    result = parse_event_decision(raw)
    assert result.confidence == 1.0

    raw_neg = """{
        "decision": "BUY",
        "confidence": -0.5,
        "reasoning": "test"
    }"""

    result_neg = parse_event_decision(raw_neg)
    assert result_neg.confidence == 0.0


async def test_parse_event_decision_nested_decision():
    """decision이 dict로 오면 result 필드에서 추출."""
    raw = """{
        "decision": {"result": "BUY"},
        "confidence": 0.7,
        "reasoning": "nested test"
    }"""

    result = parse_event_decision(raw)
    assert result.decision == "BUY"


# ─── DecisionHistory 기록 테스트 ───


async def test_make_event_decision_records_history(db: AsyncSession):
    """make_event_decision이 DecisionHistory를 올바르게 기록한다."""
    strategy = await _create_strategy(db, "history_test")
    await _create_prompt_template(db, strategy.id)
    stock_code = "000660"
    await _setup_context_data(db, stock_code, strategy.id)

    event = _make_event(stock_code, "SK하이닉스", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    mock_llm_response = """{
        "decision": "BUY",
        "confidence": 0.85,
        "reasoning": "강한 매수 신호",
        "target_return_pct": 5.0,
        "stop_pct": -3.0,
        "holding_days": 3,
        "event_assessment": "거래량 급등",
        "risk_factors": ["환율 리스크"]
    }"""

    with patch(
        "app.services.event_decision.ask_llm_by_level",
        new_callable=AsyncMock,
        return_value=mock_llm_response,
    ), patch(
        "app.services.event_decision.get_llm_level",
        new_callable=AsyncMock,
        return_value="high",
    ):
        response, history = await make_event_decision(db, event, strategy.id)

    assert isinstance(response, EventDecisionResponse)
    assert response.decision == "BUY"
    assert response.confidence == 0.85
    assert response.target_return_pct == 5.0
    assert response.stop_pct == -3.0
    assert response.holding_days == 3

    # DecisionHistory 확인
    assert isinstance(history, DecisionHistory)
    assert history.id is not None
    assert history.strategy_id == strategy.id
    assert history.stock_code == stock_code
    assert history.stock_name == "SK하이닉스"
    assert history.decision == "BUY"
    assert history.is_error is False
    assert history.error_message is None
    assert history.processing_time_ms >= 0
    assert history.request_payload != ""
    assert history.response_payload == mock_llm_response

    # parsed_decision 내용 확인
    pd = history.parsed_decision
    assert pd["decision"]["result"] == "BUY"
    assert pd["decision"]["confidence"] == 0.85
    assert pd["decision"]["target_return_pct"] == 5.0
    assert pd["decision"]["stop_pct"] == -3.0
    assert pd["decision"]["holding_days"] == 3
    assert pd["reasoning"] == "강한 매수 신호"
    assert pd["event_assessment"] == "거래량 급등"
    assert "환율 리스크" in pd["risk_factors"]


# ─── TradingEvent 상태 변경 테스트 ───


async def test_make_event_decision_updates_event_status(db: AsyncSession):
    """make_event_decision이 TradingEvent 상태를 decided로 업데이트한다."""
    strategy = await _create_strategy(db, "status_test")
    await _create_prompt_template(db, strategy.id)
    stock_code = "035720"
    await _setup_context_data(db, stock_code, strategy.id)

    event = _make_event(stock_code, "카카오", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    assert event.status == "pending"
    assert event.decision_history_id is None
    assert event.processed_at is None

    mock_llm_response = """{
        "decision": "HOLD",
        "confidence": 0.3,
        "reasoning": "불확실한 상황",
        "event_assessment": "낮은 신뢰도",
        "risk_factors": ["시장 불안"]
    }"""

    with patch(
        "app.services.event_decision.ask_llm_by_level",
        new_callable=AsyncMock,
        return_value=mock_llm_response,
    ), patch(
        "app.services.event_decision.get_llm_level",
        new_callable=AsyncMock,
        return_value="normal",
    ):
        response, history = await make_event_decision(db, event, strategy.id)

    # 상태 변경 확인
    assert event.status == "decided"
    assert event.decision_history_id == history.id
    assert event.processed_at is not None

    # HOLD 판단도 기록됨
    assert response.decision == "HOLD"
    assert history.decision == "HOLD"


async def test_make_event_decision_error_fallback(db: AsyncSession):
    """LLM 호출 실패 시 기본값(HOLD, confidence=0)으로 기록된다."""
    strategy = await _create_strategy(db, "error_test")
    await _create_prompt_template(db, strategy.id)
    stock_code = "068270"
    await _setup_context_data(db, stock_code, strategy.id)

    event = _make_event(stock_code, "셀트리온", strategy_id=strategy.id)
    db.add(event)
    await db.commit()
    await db.refresh(event)

    with patch(
        "app.services.event_decision.ask_llm_by_level",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM 호출 타임아웃"),
    ), patch(
        "app.services.event_decision.get_llm_level",
        new_callable=AsyncMock,
        return_value="high",
    ):
        response, history = await make_event_decision(db, event, strategy.id)

    # 에러 시 기본값
    assert response.decision == "HOLD"
    assert response.confidence == 0.0
    assert "타임아웃" in response.reasoning

    # 히스토리에 에러 기록
    assert history.is_error is True
    assert history.error_message is not None
    assert "타임아웃" in history.error_message
    assert history.decision == "HOLD"

    # 이벤트 상태도 decided로 변경
    assert event.status == "decided"
    assert event.decision_history_id == history.id
