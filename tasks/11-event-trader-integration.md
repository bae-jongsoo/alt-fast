# Task 11: event_trader 통합 + supervisord 등록

## 목표
Task 05~10에서 구축한 모듈들을 통합하여 `event_trader.py` 메인 프로세스를 완성하고, CLI 명령어 및 supervisord에 등록하여 페이퍼 트레이딩을 시작한다.

## 선행 조건
- Task 05~10 모두 완료

## 구현 상세

### 11.1 event_trader 메인 서비스
- `backend/app/services/event_trader.py` 생성

```python
async def run_event_trader(strategy_name: str = "event_trader"):
    """
    메인 루프:
    1. 전략 로드 (Strategy)
    2. 장 운영 시간 체크 (09:00~15:20, 매수는 15:00까지)
    3. 서킷브레이커 체크
    4. 보유 포지션 있으면 → 청산 체크 (run_liquidation_check)
    5. 이벤트 감지 (run_event_detection_loop 1회)
    6. 감지된 이벤트 → 퀀트 필터 → LLM 판단 → 매수 실행
    7. interval 대기 후 반복
    """
```

#### 메인 루프 구조
```
while True:
    if not is_market_open():
        sleep until market open
        continue

    # 1. 청산 체크 (보유 포지션)
    if has_position(strategy_id):
        await run_liquidation_check(db, strategy_id)

    # 2. 서킷브레이커
    cb = await check_circuit_breaker(db, strategy_id)
    if cb.is_active:
        log(f"서킷브레이커 활성: {cb.reason}")
        await asyncio.sleep(60)
        continue

    # 3. 이벤트 감지
    events = await detect_all_events(db, redis)

    # 4. 퀀트 필터
    passed, filtered = await filter_events(db, events, strategy_id)

    # 5. LLM 판단 + 매수 (통과 이벤트 순회)
    for event in passed:
        decision, history = await make_event_decision(db, event, strategy_id)
        if decision.decision == "BUY":
            await execute_event_buy(db, strategy_id, event, decision, history)
            break  # 1포지션 제한 — 매수 후 루프 종료

    # 6. 대기
    await asyncio.sleep(interval)  # 기본 30초
```

### 11.2 CLI 명령어
- `backend/app/cli.py`에 추가:
  - `alt trader run-event --strategy event_trader` — 이벤트 트레이더 실행
  - 기존 `alt trader run` 명령어와 별도 (기존 초단타 trader 유지)

### 11.3 supervisord 등록
- `supervisord.conf`에 `trader-event` 프로세스 추가:
```ini
[program:trader-event]
command=%(here)s/backend/.venv/bin/alt trader run-event --strategy event_trader
directory=%(here)s/backend
autostart=true
autorestart=true
stderr_logfile=/var/log/alt-fast/trader-event-error.log
stdout_logfile=/var/log/alt-fast/trader-event.log
```
- `traders` 그룹에 추가

### 11.4 event_trader 전략 초기화 스크립트
- `alt trader init-event-strategy` CLI 명령어 추가
  - Strategy 생성 (name="event_trader", initial_capital=10,000,000)
  - 기본 PromptTemplate 등록 (event_buy, event_sell)
  - 기본 SystemParameter 등록 (서킷브레이커, 필터, 사이징 파라미터)
  - TargetStock 등록 (기존 default 전략과 동일 종목 복사, 또는 수동 설정)
- 멱등성 보장 (이미 존재하면 스킵)

### 11.5 에러 핸들링 + 텔레그램 알림
- 각 단계 에러 시 catch & log (전체 루프 crash 방지)
- 중요 이벤트 텔레그램 알림:
  - 매수 체결
  - 매도 체결 (손익 포함)
  - 서킷브레이커 발동
  - LLM 호출 실패 (3회 연속)
  - 프로세스 시작/종료

### 11.6 Makefile 업데이트
- `make restart-event-trader` 추가
- `make log-event-trader` 추가

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_event_trader.py` — 메인 루프 1회 실행 테스트 (이벤트 감지 → 필터 → 판단 → 매수)
- [ ] `backend/tests/test_event_trader.py` — 서킷브레이커 활성 시 매수 스킵 테스트
- [ ] `backend/tests/test_event_trader.py` — 장 마감 시간 체크 테스트
- [ ] `backend/tests/test_event_trader.py` — 포지션 보유 시 청산 체크 실행 테스트
- [ ] `backend/tests/test_event_trader.py` — init-event-strategy 멱등성 테스트

### 수동 검증
- [ ] `uv run alt trader init-event-strategy` — 전략 초기화 성공
- [ ] `uv run alt trader run-event --strategy event_trader` — 프로세스 시작 확인
- [ ] supervisord에서 trader-event 프로세스 상태 확인
- [ ] Telegram 알림 수신 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_event_trader.py -v`

## 참고사항
- 기존 trader-default 프로세스는 그대로 유지 (독립 운영)
- 초기 배포 후 supervisord에서 autostart=false로 설정하고, 수동 테스트 후 활성화 권장
- 매수 시간 제한: 15:00 이후 신규 매수 금지 (장 마감 30분 전)
- 이 태스크 완료 = Phase 2 완료 → 페이퍼 트레이딩 시작
