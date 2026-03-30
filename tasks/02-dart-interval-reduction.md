# Task 02: DART 수집 주기 단축 + 신규 공시 감지 플래그

## 목표
기존 DART 수집 주기를 600초(10분)에서 600초로 유지하되, 시스템 파라미터로 설정 가능하게 만들고, 신규 공시를 감지할 수 있는 플래그(`is_new`)를 추가하여 event_trader가 새 공시를 효율적으로 감지할 수 있도록 한다.

## 선행 조건
- Task 01 완료 (DB 마이그레이션 체인 유지)

## 구현 상세

### 2.1 DartDisclosure 모델에 `is_processed` 플래그 추가
- `backend/app/models/dart_disclosure.py`에 컬럼 추가:
  - `is_processed` (Boolean, default=False) — event_trader가 처리 완료 시 True로 변경
- Alembic 마이그레이션 생성 및 적용

### 2.2 DART 수집 주기 시스템 파라미터화
- 현재 `cli.py`에서 `_get_system_param(session, "dart_collect_interval", "600")` 형태로 이미 파라미터화되어 있는지 확인
- 없다면 `dart_collect_interval` 시스템 파라미터 추가 (기본값 600, 추후 UI에서 변경 가능)
- 장중(09:00~15:30)에는 더 짧은 주기 적용 가능하도록 `dart_collect_interval_market_hours` 파라미터 추가 (기본값 600)

### 2.3 수집 시 신규 감지 로직 강화
- `backend/app/services/dart_collector.py` 수정:
  - 수집 시 기존 DB에 없는 공시만 INSERT (현재 로직 유지)
  - 새로 INSERT된 공시에는 `is_processed=False` 설정
  - 수집 결과에 신규 공시 건수 로깅 추가
  - 신규 공시 발생 시 Redis pub/sub 또는 키로 알림 (event_trader가 폴링 대신 즉시 감지 가능하도록)
    - Redis 키: `event:dart:new` (List, 신규 공시 ID를 RPUSH)

### 2.4 신규 공시 조회 헬퍼 함수
- `backend/app/services/dart_collector.py`에 추가:
  - `async def get_unprocessed_disclosures(db, stock_codes=None, limit=10) -> list[DartDisclosure]`
  - `async def mark_disclosure_processed(db, disclosure_id: int)`

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_dart_collector.py` — is_processed 플래그 동작 테스트 (생성 시 False, mark 후 True)
- [ ] `backend/tests/test_dart_collector.py` — get_unprocessed_disclosures() 필터링 테스트
- [ ] `backend/tests/test_dart_collector.py` — 수집 시 신규 공시 감지 및 Redis 알림 테스트 (Redis mock)

### 수동 검증
- [ ] `uv run alembic upgrade head` 성공
- [ ] `uv run alt dart collect` 실행 후 DB에서 `is_processed=False` 데이터 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_dart_collector.py -v`

## 참고사항
- 복합 공시(M&A 등)는 시장 소화에 30분~수시간 걸리므로 10분 간격 수집으로 충분
- Redis pub/sub 대신 List(RPUSH/BLPOP)를 사용하면 event_trader가 다운되어도 메시지 유실 없음
- 이 태스크의 `is_processed` 플래그와 Redis 알림은 Task 05(이벤트 감지)에서 사용됨
