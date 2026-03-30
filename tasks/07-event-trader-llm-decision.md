# Task 07: event_trader LLM 판단 모듈

## 목표
이벤트 컨텍스트 + 거시 데이터 + 관련 뉴스를 LLM 프롬프트에 포함하여 매수/관망 판단을 받는 모듈을 구축한다. LLM은 confidence score, 목표가, 손절가, 예상 보유기간을 함께 출력한다. 기존 trader.py의 프롬프트 구조를 참고하되, 이벤트 드리븐에 맞게 재설계한다.

## 선행 조건
- Task 01 완료 (MacroSnapshot)
- Task 05 완료 (TradingEvent)
- Task 06 완료 (퀀트 필터)

## 구현 상세

### 7.1 LLM 응답 스키마 정의
- `backend/app/schemas/event_decision.py` 생성
```python
class EventDecisionResponse(BaseModel):
    decision: Literal["BUY", "HOLD"]  # 이벤트 기반이므로 SELL 없음 (청산은 별도)
    confidence: float  # 0.0 ~ 1.0
    reasoning: str  # 판단 근거
    target_return_pct: float | None  # 목표 수익률 (예: 3.0 → 3%)
    stop_pct: float | None  # 손절 수준 (예: -2.0 → -2%)
    holding_days: int | None  # 예상 보유 기간 (일)
    event_assessment: str  # 이벤트에 대한 평가
    risk_factors: list[str]  # 리스크 요인
```

### 7.2 이벤트 판단 프롬프트 템플릿
- DB `prompt_templates` 테이블에 event_trader 전략용 프롬프트 등록
- 프롬프트에 포함할 컨텍스트:
  1. **이벤트 정보**: 이벤트 유형, 상세 데이터, 감지 시각
  2. **종목 기본 정보**: 시가총액, PER, PBR, 52주 고저, 외국인 비중 (MarketSnapshot)
  3. **거시 데이터**: 미장 지수, 환율, 금리, VIX (MacroSnapshot — 당일 최신)
  4. **관련 뉴스**: 해당 종목 최근 뉴스 (News, 최대 5건)
  5. **관련 공시**: 해당 종목 최근 공시 (DartDisclosure, 최대 3건)
  6. **가격 데이터**: 최근 30분봉 (MinuteCandle)
  7. **호가 정보**: 최신 호가 스프레드 (OrderbookSnapshot)
  8. **현재 포트폴리오**: 보유 현금, 기존 포지션 현황
- 프롬프트는 Jinja2 템플릿 (기존 trader.py 패턴 따름)

### 7.3 이벤트 판단 서비스
- `backend/app/services/event_decision.py` 생성

```python
async def build_event_prompt(
    db: AsyncSession,
    event: TradingEvent,
    strategy_id: int
) -> str:
    """이벤트 컨텍스트를 수집하여 프롬프트 조합"""

async def make_event_decision(
    db: AsyncSession,
    event: TradingEvent,
    strategy_id: int
) -> tuple[EventDecisionResponse, DecisionHistory]:
    """
    1. build_event_prompt()
    2. ask_llm_by_level() 호출
    3. 응답 파싱 (JSON → EventDecisionResponse)
    4. DecisionHistory 기록
    5. TradingEvent status 업데이트 → "sent_to_llm" → "decided"
    """
```

### 7.4 LLM 응답 파싱 강화
- `backend/app/shared/json_helpers.py`의 기존 `parse_llm_json_object()` 활용
- confidence, target_return_pct, stop_pct, holding_days 파싱 추가
- 파싱 실패 시 기본값 적용: confidence=0 (→ HOLD 처리), 나머지 None

### 7.5 DecisionHistory 확장
- 기존 `parsed_decision` JSON 필드에 confidence, target_return_pct, stop_pct, holding_days 저장
- 새 컬럼 추가 불필요 (JSON 필드 활용)

### 7.6 Strategy 및 PromptTemplate 초기 데이터
- `event_trader` 전략 생성 (Strategy 테이블)
- 해당 전략의 프롬프트 템플릿 등록 (prompt_type="event_buy")
- Alembic 데이터 마이그레이션 또는 시드 스크립트

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_event_decision.py` — 프롬프트 빌드 테스트 (이벤트 + 매크로 + 뉴스 포함 확인)
- [ ] `backend/tests/test_event_decision.py` — LLM 응답 파싱 테스트 (정상 JSON → EventDecisionResponse)
- [ ] `backend/tests/test_event_decision.py` — 파싱 실패 시 기본값 적용 테스트
- [ ] `backend/tests/test_event_decision.py` — DecisionHistory 기록 테스트
- [ ] `backend/tests/test_event_decision.py` — TradingEvent 상태 변경 테스트

### 수동 검증
- [ ] `event_trader` 전략 및 프롬프트 템플릿 DB 등록 확인
- [ ] 프롬프트 내용이 이벤트 컨텍스트를 적절히 포함하는지 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_event_decision.py -v`

## 참고사항
- confidence score는 초기에 캘리브레이션되지 않음 → 모든 값을 기록하고 Phase 3에서 사후 검증
- LLM이 HOLD 판단 시에도 reasoning과 event_assessment는 기록 (향후 분석용)
- 프롬프트에 "거시 레짐 판단" 모듈을 별도로 만들지 않고, 거시 데이터를 프롬프트에 매번 포함하여 LLM이 알아서 감안하도록 함
- 기존 trader.py의 프롬프트 빌드 패턴(_build_stock_prompt_context 등)을 참고하되, 이벤트 중심으로 재구성
