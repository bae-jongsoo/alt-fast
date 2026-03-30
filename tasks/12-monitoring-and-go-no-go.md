# Task 12: 모니터링 대시보드 + Go/No-Go 게이트

## 목표
event_trader의 성과를 모니터링하는 API와 Go/No-Go 게이트 자동 체크 기능을 구축한다. confidence 구간별 승률, 이벤트 유형별 성과 등 Phase 3 측정 항목을 추적한다.

## 선행 조건
- Task 11 완료 (event_trader 통합)

## 구현 상세

### 12.1 성과 분석 서비스
- `backend/app/services/event_performance.py` 생성

```python
@dataclass
class PerformanceMetrics:
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float  # 총 이익 / 총 손실
    kelly_pct: float
    avg_profit_rate: float
    avg_loss_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float | None
    by_event_type: dict[str, EventTypeMetrics]
    by_confidence_bucket: dict[str, ConfidenceBucketMetrics]

async def calculate_performance(
    db: AsyncSession,
    strategy_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PerformanceMetrics:
```

#### 12.1.1 이벤트 유형별 성과
- OrderHistory → TradingEvent (event_id) JOIN → event_type별 그룹핑
- 각 유형별: 거래 건수, 승률, 평균 수익률, PF

#### 12.1.2 Confidence 구간별 성과
- DecisionHistory의 parsed_decision → confidence 추출
- 구간: 0~0.3, 0.3~0.5, 0.5~0.7, 0.7~1.0
- 각 구간별: 거래 건수, 승률, 평균 수익률

### 12.2 Go/No-Go 게이트 체크
```python
@dataclass
class GateResult:
    gate_level: str  # "20", "50", "100"
    passed: bool
    details: dict
    recommendation: str  # "continue", "stop", "review"

async def check_go_no_go_gate(
    db: AsyncSession,
    strategy_id: int,
) -> GateResult | None:
```

게이트 조건:
| 레벨 | 조건 | 실패 시 |
|------|------|---------|
| **20건** | PF < 0.5 또는 승률 < 15% | 즉시 중단 권고 |
| **50건** | PF ≥ 1.2, 승률 ≥ 38%, Kelly% ≥ +0.05 | 파라미터 수정 후 재시도 (최대 2회) |
| **100건** | 전반/후반 50건 괴리 < 30% | 실매매 전환 검토 가능 |

- 각 게이트 도달 시 자동 체크 + Telegram 알림
- 게이트 실패 횟수 추적: `system_parameter`에 `gate_50_fail_count` 저장

### 12.3 API 엔드포인트
- `backend/app/api/event_trader.py` 생성

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/event-trader/performance` | GET | 전체 성과 지표 |
| `/api/event-trader/performance/by-event-type` | GET | 이벤트 유형별 성과 |
| `/api/event-trader/performance/by-confidence` | GET | Confidence 구간별 성과 |
| `/api/event-trader/events` | GET | 최근 이벤트 목록 (필터: status, type) |
| `/api/event-trader/gate` | GET | Go/No-Go 게이트 상태 |
| `/api/event-trader/circuit-breaker` | GET | 서킷브레이커 상태 |
| `/api/event-trader/circuit-breaker/reset` | POST | 서킷브레이커 수동 리셋 |

- 라우터를 `backend/app/api/router.py`에 등록

### 12.4 일일 리포트에 event_trader 성과 포함
- 기존 `daily_review.py` 또는 `report/` 서비스 수정
- event_trader 전략의 당일 성과 섹션 추가
- Telegram 리포트에 포함

### 12.5 게이트 자동 체크 통합
- event_trader 메인 루프에서 매수 체결 후 거래 건수 체크
- 게이트 레벨 도달 시 `check_go_no_go_gate()` 실행
- 실패 시 Telegram 알림 + 서킷브레이커 강제 활성화 (20건 게이트 실패)

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_event_performance.py` — 승률, PF, Kelly% 계산 정확성 테스트
- [ ] `backend/tests/test_event_performance.py` — 이벤트 유형별 그룹핑 테스트
- [ ] `backend/tests/test_event_performance.py` — Confidence 구간별 그룹핑 테스트
- [ ] `backend/tests/test_event_performance.py` — Go/No-Go 20건 게이트 테스트 (PF < 0.5 → 실패)
- [ ] `backend/tests/test_event_performance.py` — Go/No-Go 50건 게이트 테스트 (조건 충족/미충족)
- [ ] `backend/tests/test_event_performance.py` — Go/No-Go 100건 게이트 테스트 (전반/후반 괴리)

### 수동 검증
- [ ] `curl localhost:8000/api/event-trader/performance` — 성과 API 응답 확인
- [ ] `curl localhost:8000/api/event-trader/gate` — 게이트 상태 API 응답 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_event_performance.py -v`

## 참고사항
- 초기에는 데이터가 적어 통계적 유의성 없음 — 참고 지표로만 활용
- Phase 3에서 데이터 축적되면 confidence 캘리브레이션, 슬리피지 분석 추가 예정
- 프론트엔드 대시보드는 별도 태스크로 분리 (현재는 API만 제공)
- 이 태스크 완료 = Phase 2 + 모니터링 완비 → 본격 페이퍼 운영 시작
