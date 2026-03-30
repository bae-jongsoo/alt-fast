# Task 09: 청산 로직

## 목표
LLM이 매수 시 제시한 목표가/손절가/보유기간을 기반으로 보유 포지션을 청산하는 로직을 구축한다. 기계적 안전장치(-2% 강제 손절)를 포함하고, 이벤트 유형에 따른 청산 전략 차이를 프롬프트 가이드라인으로 반영한다.

## 선행 조건
- Task 08 완료 (포지션 사이징 + 매수 실행, target_return_pct/stop_pct/holding_days 저장)

## 구현 상세

### 9.1 청산 판단 서비스
- `backend/app/services/event_liquidator.py` 생성

#### 9.1.1 기계적 청산 체크 (LLM 호출 없음, 우선 실행)
```python
@dataclass
class LiquidationSignal:
    should_liquidate: bool
    reason: str
    signal_type: str  # "mechanical_stop", "mechanical_target", "mechanical_expiry", "llm_decision"

async def check_mechanical_liquidation(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    current_price: Decimal,
) -> LiquidationSignal | None:
```

조건 (하나라도 만족하면 즉시 청산):
| 조건 | 기준 | 설명 |
|------|------|------|
| **강제 손절** | 현재가 ≤ 매수가 * (1 + stop_pct/100) 또는 -2% 중 먼저 도달 | 기계적 안전장치 |
| **목표 도달** | 현재가 ≥ 매수가 * (1 + target_return_pct/100) | LLM 제시 목표가 |
| **보유기간 초과** | 보유일 > holding_days * 1.5 | 예상 보유기간의 1.5배 초과 시 강제 청산 |

- stop_pct이 None이면 시스템 기본값 -2% 적용 (시스템 파라미터 `event_trader_default_stop_pct`)
- target_return_pct이 None이면 기계적 목표 청산 비활성화
- holding_days가 None이면 기계적 기간 청산 비활성화

#### 9.1.2 LLM 기반 청산 판단 (기계적 청산 미해당 시)
```python
async def check_llm_liquidation(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    event: TradingEvent | None,
) -> LiquidationSignal | None:
```
- 보유기간 ≥ holding_days 도달 시 LLM에 청산 판단 요청
- 프롬프트에 포함:
  - 매수 근거 (원본 이벤트, buy reasoning)
  - 현재 수익률
  - 최근 관련 뉴스/공시 (이벤트 진행 상황)
  - 거시 데이터
- LLM 응답: SELL / HOLD + reasoning
- LLM 호출 빈도 제한: 동일 포지션에 대해 1시간 1회 (DecisionHistory 체크)

#### 9.1.3 청산 실행
```python
async def execute_event_sell(
    db: AsyncSession,
    strategy_id: int,
    position: Asset,
    buy_order: OrderHistory,
    signal: LiquidationSignal,
    current_price: Decimal,
) -> OrderHistory:
    """
    1. apply_virtual_sell() (기존 asset_manager 활용)
    2. OrderHistory 생성 (profit_loss, profit_rate, net 계산)
    3. buy_order_id 연결
    4. TradingEvent 상태 업데이트
    5. Telegram 알림 (청산 정보 + 손익)
    """
```

### 9.2 청산 체크 루프
```python
async def run_liquidation_check(db: AsyncSession, strategy_id: int):
    """
    보유 포지션이 있으면:
    1. 기계적 청산 체크 (즉시)
    2. 해당 없으면 → 보유기간 도달 시 LLM 청산 판단
    3. 청산 신호 발생 시 → execute_event_sell()
    """
```
- event_trader 메인 루프에서 이벤트 감지와 함께 주기적으로 실행 (1분 간격)

### 9.3 프롬프트 템플릿 등록
- `event_sell` 프롬프트 템플릿을 DB에 등록
- 이벤트 유형별 가이드라인을 프롬프트에 포함 (하드코딩 아닌 참고용):
  - 복합 공시(M&A): trailing stop 활용, 보유 수일
  - PEAD(실적): trailing 넓게, 보유 수일~수주
  - 뉴스 클러스터: 목표가 도달 시 부분 청산
  - 2차 연관종목: 빠른 익절

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_event_liquidator.py` — 강제 손절 테스트 (-2% 도달 → 즉시 청산)
- [ ] `backend/tests/test_event_liquidator.py` — 목표가 도달 테스트 (target_return_pct 도달 → 청산)
- [ ] `backend/tests/test_event_liquidator.py` — 보유기간 초과 테스트 (holding_days * 1.5 → 강제 청산)
- [ ] `backend/tests/test_event_liquidator.py` — 기계적 청산 미해당 시 LLM 판단 호출 테스트
- [ ] `backend/tests/test_event_liquidator.py` — LLM 호출 빈도 제한 테스트 (1시간 1회)
- [ ] `backend/tests/test_event_liquidator.py` — execute_event_sell() 통합 테스트 (가상 매도 + 손익 계산)

### 수동 검증
- [ ] 프롬프트 템플릿 (event_sell) DB 등록 확인
- [ ] Telegram 알림 메시지 형식 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_event_liquidator.py -v`

## 참고사항
- -2% 손절은 LLM 판단과 무관하게 강제 적용 (기계적 안전장치)
- LLM의 stop_pct이 -2%보다 타이트하면 LLM 값 사용, 느슨하면 -2% 적용
- 부분 청산은 현재 미지원 (전량 청산만). 멀티 포지션 지원 시 함께 추가
- 현재가 조회: MarketSnapshot 최신 또는 Redis 실시간 데이터 활용
