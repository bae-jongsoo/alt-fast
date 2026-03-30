# Task 10: 서킷브레이커

## 목표
연속 손실, 일일 손실 한도, 일일 매매 상한 등의 안전장치를 구축하여 event_trader의 과도한 손실을 방지한다.

## 선행 조건
- Task 08 완료 (매수 실행)
- Task 09 완료 (청산 로직)

## 구현 상세

### 10.1 서킷브레이커 서비스
- `backend/app/services/circuit_breaker.py` 생성

```python
@dataclass
class CircuitBreakerStatus:
    is_active: bool       # True면 매매 차단
    reason: str | None
    remaining_trades: int  # 남은 매매 가능 횟수
    daily_loss: Decimal    # 금일 누적 손실
    consecutive_losses: int

async def check_circuit_breaker(
    db: AsyncSession,
    strategy_id: int,
) -> CircuitBreakerStatus:
```

### 10.2 서킷브레이커 조건

| 조건 | 기준 | 복구 | 시스템 파라미터 |
|------|------|------|----------------|
| **3연패 정지** | 연속 3회 손실 (profit_loss < 0) | 당일 자동 해제 안 됨, 수동 리셋 또는 익일 자동 해제 | `cb_max_consecutive_losses` (기본 3) |
| **일일 손실 한도** | 당일 실현 손실 합계 ≥ 총 자산의 3% | 익일 자동 해제 | `cb_daily_loss_limit_pct` (기본 3.0) |
| **일일 매매 상한** | 당일 매수 체결 건수 ≥ 5건 | 익일 자동 해제 | `cb_max_daily_trades` (기본 5) |

### 10.3 구현 세부

#### 연속 손실 카운트
- 해당 전략의 최근 OrderHistory (order_type="SELL") 조회
- 연속 profit_loss < 0 건수 카운트
- 마지막 수익 매매 이후 연속 손실만 카운트

#### 일일 손실 합계
- 당일(KST 기준) SELL 주문의 profit_loss_net 합계
- 총 자산 = 전략의 initial_capital (또는 현재 총 자산 = 현금 + 보유종목 평가액)

#### 일일 매매 건수
- 당일(KST 기준) BUY 주문 건수

### 10.4 서킷브레이커 상태 Redis 캐싱
- Redis 키: `circuit_breaker:{strategy_id}` (Hash)
  - `is_active`: "1" / "0"
  - `reason`: 차단 사유
  - `activated_at`: 활성화 시각
- TTL: 익일 00:00까지 (일일 리셋)
- 3연패는 Redis + DB 양쪽 체크 (Redis는 빠른 조회용)

### 10.5 수동 리셋
- `async def reset_circuit_breaker(db, strategy_id)` — 수동 해제
- API 엔드포인트: `POST /api/event-trader/circuit-breaker/reset` (인증 필요)

### 10.6 서킷브레이커 통합
- event_trader 메인 루프에서 이벤트 처리 전 `check_circuit_breaker()` 호출
- is_active=True면 이벤트를 "pending" 상태로 유지 (expire 전까지 대기)
- 서킷브레이커 발동 시 Telegram 알림

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_circuit_breaker.py` — 3연패 감지 테스트 (3회 연속 손실 → is_active=True)
- [ ] `backend/tests/test_circuit_breaker.py` — 일일 손실 한도 테스트 (3% 초과 → is_active=True)
- [ ] `backend/tests/test_circuit_breaker.py` — 일일 매매 상한 테스트 (5건 초과 → is_active=True)
- [ ] `backend/tests/test_circuit_breaker.py` — 정상 상태 테스트 (모든 조건 미충족 → is_active=False)
- [ ] `backend/tests/test_circuit_breaker.py` — 수동 리셋 테스트
- [ ] `backend/tests/test_circuit_breaker.py` — 연속 손실 카운트 정확성 (중간에 수익 있으면 리셋)

### 수동 검증
- [ ] `curl -X POST localhost:8000/api/event-trader/circuit-breaker/reset` — 리셋 API 동작 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_circuit_breaker.py -v`

## 참고사항
- 서킷브레이커는 보수적으로 운영 (일 5건도 초기에는 많을 수 있음)
- 3연패 정지는 "이 전략이 현재 시장에 맞지 않는다"는 신호 — 수동 검토 후 리셋
- Phase 3에서 Go/No-Go 게이트와 연계하여 조건 조정 가능
