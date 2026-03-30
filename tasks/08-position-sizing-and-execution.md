# Task 08: 포지션 사이징 + 매수 실행

## 목표
LLM이 BUY 판단을 내린 이벤트에 대해 적절한 포지션 크기를 결정하고 가상 매수를 실행한다. 초기에는 고정 소액으로 시작하되, 데이터가 쌓이면 confidence 기반 사이징으로 전환할 수 있는 구조를 만든다. Half-Kelly 캡을 적용한다.

## 선행 조건
- Task 07 완료 (LLM 판단 모듈, EventDecisionResponse)

## 구현 상세

### 8.1 포지션 사이징 서비스
- `backend/app/services/position_sizer.py` 생성

```python
@dataclass
class SizingResult:
    quantity: int           # 매수 수량
    total_amount: Decimal   # 총 매수 금액
    sizing_method: str      # "fixed" 또는 "kelly"
    kelly_fraction: float | None
    details: dict           # 계산 과정

async def calculate_position_size(
    db: AsyncSession,
    strategy_id: int,
    stock_code: str,
    current_price: Decimal,
    confidence: float,
    target_return_pct: float | None,
    stop_pct: float | None,
) -> SizingResult:
```

#### 8.1.1 고정 소액 모드 (초기)
- 시스템 파라미터 `event_trader_fixed_amount` (기본 500,000원)
- `quantity = fixed_amount // current_price`
- 보유 현금 체크: 현금 부족 시 수량 축소 또는 매수 포기

#### 8.1.2 Kelly 기반 모드 (데이터 축적 후)
- 시스템 파라미터 `event_trader_sizing_mode` ("fixed" / "kelly", 기본 "fixed")
- Kelly% = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
- Half-Kelly 적용: `fraction = kelly% / 2`
- confidence 반영: `fraction *= confidence`
- 캡: `fraction = min(fraction, 0.1)` (최대 총 자산의 10%)
- `total_amount = total_capital * fraction`
- win_rate, avg_win, avg_loss는 해당 전략의 과거 OrderHistory에서 계산

#### 8.1.3 안전장치
- 단일 종목 최대 투자 비중: 총 자산의 20% (시스템 파라미터화)
- 최소 잔여 현금: 총 자산의 10% (현금 고갈 방지)
- 매수 금액 ≤ 0 시 매수 포기

### 8.2 매수 실행 함수
```python
async def execute_event_buy(
    db: AsyncSession,
    strategy_id: int,
    event: TradingEvent,
    decision: EventDecisionResponse,
    decision_history: DecisionHistory,
) -> OrderHistory | None:
    """
    1. calculate_position_size()
    2. 수량 0 → None 반환 (매수 포기)
    3. apply_virtual_buy() (기존 asset_manager 활용)
    4. OrderHistory 생성 (decision_history_id 연결)
    5. TradingEvent에 결과 기록
    6. Telegram 알림 (매수 실행 정보)
    """
```

### 8.3 OrderHistory에 이벤트 정보 저장
- 기존 OrderHistory에 `event_id` 컬럼 추가 (FK → trading_events.id, nullable)
  - 기존 trader의 주문은 event_id=None
- Alembic 마이그레이션

### 8.4 매수 시 목표가/손절가 저장
- OrderHistory의 기존 JSON 필드 또는 새 컬럼에 저장:
  - `target_return_pct` (Numeric, nullable)
  - `stop_pct` (Numeric, nullable)
  - `holding_days` (Integer, nullable)
- Alembic 마이그레이션
- 이 값들은 Task 09(청산 로직)에서 사용

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_position_sizer.py` — 고정 소액 모드 계산 테스트 (50만원, 주가 10,000원 → 50주)
- [ ] `backend/tests/test_position_sizer.py` — 현금 부족 시 수량 축소 테스트
- [ ] `backend/tests/test_position_sizer.py` — Kelly 모드 계산 테스트 (win_rate, avg_win/loss 기반)
- [ ] `backend/tests/test_position_sizer.py` — Half-Kelly 캡 적용 테스트
- [ ] `backend/tests/test_position_sizer.py` — 최대 투자 비중 제한 테스트
- [ ] `backend/tests/test_position_sizer.py` — execute_event_buy() 통합 테스트 (가상 매수 + OrderHistory 생성)

### 수동 검증
- [ ] `uv run alembic upgrade head` 성공
- [ ] 시스템 파라미터 조회 확인 (event_trader_fixed_amount, event_trader_sizing_mode)

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_position_sizer.py -v`

## 참고사항
- 초기에는 반드시 "fixed" 모드로 운영. Kelly 모드는 최소 50건 매매 이력 필요
- confidence 기반 사이징은 confidence 캘리브레이션 후 전환 (Phase 3)
- 기존 asset_manager.py의 apply_virtual_buy()를 그대로 활용 (코드 재사용)
- 멀티 포지션은 현재 지원하지 않음 (결정사항 5번) — 전략별 1포지션 유지
