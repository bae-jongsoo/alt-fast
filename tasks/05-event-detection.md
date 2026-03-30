# Task 05: 이벤트 감지 모듈

## 목표
event_trader의 핵심 입력부인 이벤트 감지 모듈을 구축한다. 세 가지 이벤트 소스(신규 공시, 뉴스 클러스터, 거래량 급증)를 모니터링하고, 감지된 이벤트를 통합 이벤트 큐에 적재한다.

## 선행 조건
- Task 02 완료 (DART is_processed 플래그, Redis 알림)
- Task 03 완료 (뉴스 클러스터링)

## 구현 상세

### 5.1 이벤트 모델 생성
- `backend/app/models/trading_event.py` 생성
- 필드:
  - `id` (PK)
  - `event_type` (String) — "dart_disclosure", "news_cluster", "volume_spike"
  - `stock_code` (String)
  - `stock_name` (String)
  - `event_data` (JSON) — 이벤트별 상세 데이터
    - dart: disclosure_id, disclosure_type, title
    - news_cluster: cluster_id, news_count, keyword
    - volume_spike: current_volume, avg_volume, spike_ratio
  - `confidence_hint` (Numeric, nullable) — 이벤트 자체의 중요도 힌트 (0~1)
  - `status` (String, default="pending") — "pending", "filtered", "sent_to_llm", "decided", "expired"
  - `strategy_id` (Integer, FK, nullable) — 처리한 전략
  - `decision_history_id` (Integer, FK, nullable) — 연결된 매매 판단
  - `detected_at` (DateTime)
  - `processed_at` (DateTime, nullable)
  - `created_at` (DateTime)
- Alembic 마이그레이션

### 5.2 이벤트 감지 서비스
- `backend/app/services/event_detector.py` 생성

#### 5.2.1 공시 이벤트 감지
```python
async def detect_dart_events(db: AsyncSession) -> list[TradingEvent]:
```
- Redis `event:dart:new` 리스트에서 BLPOP (타임아웃 1초)
- 또는 DB에서 `is_processed=False` 공시 조회
- 공시 유형별 confidence_hint 설정:
  - M&A, 대규모 계약: 0.8
  - 실적 공시: 0.7
  - 임원 변경, 유상증자: 0.5
  - 기타: 0.3

#### 5.2.2 뉴스 클러스터 이벤트 감지
```python
async def detect_news_cluster_events(db: AsyncSession) -> list[TradingEvent]:
```
- Redis `event:news_cluster:new` 리스트에서 BLPOP
- 또는 DB에서 `is_processed=False` 클러스터 조회
- 뉴스 건수에 따라 confidence_hint 설정 (3건: 0.3, 5건+: 0.6, 10건+: 0.8)

#### 5.2.3 거래량 급증 감지
```python
async def detect_volume_spike_events(db: AsyncSession, redis) -> list[TradingEvent]:
```
- Redis에서 최근 분봉 데이터 조회 (ws_collector가 저장한 실시간 데이터)
- 최근 5분 거래량 vs 전일 동시간대 평균 거래량 비교
- 2배 이상 급증 시 이벤트 생성
- 전일 평균 거래량은 DB의 MinuteCandle에서 계산
- spike_ratio에 따라 confidence_hint: 2x→0.3, 5x→0.6, 10x+→0.8

#### 5.2.4 통합 이벤트 루프
```python
async def run_event_detection_loop(db: AsyncSession, redis, interval_seconds: int = 30):
```
- 30초 간격으로 세 가지 감지 함수를 병렬 실행 (`asyncio.gather`)
- 중복 이벤트 필터링 (동일 종목 + 동일 타입 + 10분 이내 → 기존 이벤트 업데이트)
- 감지된 이벤트를 DB에 저장 (status="pending")
- 이벤트 로깅

### 5.3 이벤트 조회 헬퍼
```python
async def get_pending_events(db, strategy_id=None, limit=10) -> list[TradingEvent]
async def update_event_status(db, event_id, status, decision_history_id=None)
async def expire_old_events(db, max_age_hours=4)  # 장중 미처리 이벤트 만료
```

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_event_detector.py` — 공시 이벤트 감지 테스트 (미처리 공시 → TradingEvent 생성)
- [ ] `backend/tests/test_event_detector.py` — 뉴스 클러스터 이벤트 감지 테스트
- [ ] `backend/tests/test_event_detector.py` — 거래량 급증 감지 테스트 (분봉 데이터 기반)
- [ ] `backend/tests/test_event_detector.py` — 중복 이벤트 필터링 테스트 (10분 이내 동일 이벤트)
- [ ] `backend/tests/test_event_detector.py` — 이벤트 상태 변경 및 만료 테스트

### 수동 검증
- [ ] `uv run alembic upgrade head` 성공
- [ ] 이벤트 감지 루프가 에러 없이 동작 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_event_detector.py -v`

## 참고사항
- 거래량 급증 감지는 Redis의 실시간 데이터에 의존하므로 ws_collector가 동작 중이어야 함
- 테스트에서는 Redis를 fakeredis로 모킹
- 이 모듈은 Task 06(퀀트 필터)과 Task 07(LLM 판단)에서 사용됨
- 이벤트 감지 루프는 event_trader 프로세스 내에서 실행됨 (별도 프로세스 아님)
