# Task 06: 퀀트 필터

## 목표
이벤트 감지 모듈이 생성한 이벤트를 LLM 호출 전에 룰 기반으로 필터링한다. 거래량, 호가 스프레드, 시총 등을 체크하여 매매 부적합 종목을 사전에 걸러낸다. LLM 호출 비용과 시간을 절약하는 게이트키퍼 역할.

## 선행 조건
- Task 05 완료 (이벤트 감지 모듈, TradingEvent 모델)

## 구현 상세

### 6.1 퀀트 필터 서비스
- `backend/app/services/quant_filter.py` 생성

#### 6.1.1 필터 함수
```python
@dataclass
class FilterResult:
    passed: bool
    reason: str | None  # 필터링된 사유
    metrics: dict       # 체크한 수치들

async def apply_quant_filter(db: AsyncSession, event: TradingEvent) -> FilterResult:
```

#### 6.1.2 필터 조건 (모두 통과해야 LLM 전달)

| 필터 | 조건 | 데이터 소스 | 설명 |
|------|------|-----------|------|
| **거래량** | 당일 거래량 ≥ 전일 평균의 2배 | MinuteCandle (당일 누적) vs DB (전일) | 유동성 부족 방지 |
| **호가 스프레드** | 스프레드 ≤ 0.5% | OrderbookSnapshot (최신) | 슬리피지 과다 방지 |
| **시가총액** | 시총 ≥ 500억 | MarketSnapshot | 소형주 리스크 방지 |
| **가격** | 주가 ≥ 1,000원 | MarketSnapshot | 동전주 제외 |
| **거래정지** | 거래정지 아님 | MarketSnapshot | — |
| **기존 포지션** | 해당 전략에 동일 종목 미보유 | Asset | 중복 매수 방지 |

#### 6.1.3 필터 파라미터 시스템 파라미터화
- `quant_filter_min_volume_ratio` (기본 2.0)
- `quant_filter_max_spread_pct` (기본 0.5)
- `quant_filter_min_market_cap` (기본 50000000000, 500억)
- `quant_filter_min_price` (기본 1000)
- 모두 SystemParameter에서 읽어 UI에서 변경 가능

### 6.2 배치 필터 함수
```python
async def filter_events(db: AsyncSession, events: list[TradingEvent], strategy_id: int) -> tuple[list[TradingEvent], list[TradingEvent]]:
    """
    Returns: (passed_events, filtered_events)
    필터링된 이벤트는 status='filtered'로 업데이트하고 reason 기록
    """
```

### 6.3 필터 결과 기록
- TradingEvent의 `event_data`에 filter_result 추가 (metrics, reason)
- 필터링된 이벤트는 `status="filtered"`로 변경
- 통과한 이벤트는 `status="pending"` 유지 (다음 단계에서 처리)

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_quant_filter.py` — 거래량 필터 테스트 (2배 미만 → 필터링)
- [ ] `backend/tests/test_quant_filter.py` — 호가 스프레드 필터 테스트 (0.5% 초과 → 필터링)
- [ ] `backend/tests/test_quant_filter.py` — 시총 필터 테스트 (500억 미만 → 필터링)
- [ ] `backend/tests/test_quant_filter.py` — 모든 조건 통과 시 passed=True
- [ ] `backend/tests/test_quant_filter.py` — 기존 포지션 중복 체크 테스트
- [ ] `backend/tests/test_quant_filter.py` — 배치 필터 동작 및 상태 업데이트 테스트

### 수동 검증
- [ ] 필터 파라미터를 SystemParameter에서 조회/변경 가능 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_quant_filter.py -v`

## 참고사항
- 퀀트 필터는 LLM 호출 없이 순수 룰 기반으로 동작 (빠름, 비용 0)
- 필터 조건은 보수적으로 시작하고, 페이퍼 트레이딩 결과를 보며 조정
- 호가 스프레드 데이터가 없는 경우(OrderbookSnapshot이 비어있으면) 해당 필터는 패스 처리
- 이 모듈은 Task 07(LLM 판단)에서 사용됨
