# Task 03: 뉴스 클러스터링 로직 추가

## 목표
기존 뉴스 수집 파이프라인에 동일 종목/테마 뉴스를 그룹핑하는 클러스터링 로직을 추가한다. 특정 종목에 대해 단시간 내 다수의 뉴스가 쏟아지는 "뉴스 클러스터" 이벤트를 감지할 수 있도록 한다.

## 선행 조건
- Task 01, 02 완료 (DB 마이그레이션 체인)

## 구현 상세

### 3.1 NewsCluster 모델 생성
- `backend/app/models/news_cluster.py` 생성
- 필드:
  - `id` (PK)
  - `stock_code` (String) — 관련 종목 코드
  - `stock_name` (String)
  - `cluster_type` (String) — "volume" (건수 기반), "theme" (테마 기반)
  - `keyword` (String, nullable) — 클러스터 핵심 키워드
  - `news_count` (Integer) — 클러스터에 포함된 뉴스 수
  - `first_news_at` (DateTime) — 클러스터 내 첫 뉴스 시각
  - `last_news_at` (DateTime) — 클러스터 내 마지막 뉴스 시각
  - `is_processed` (Boolean, default=False) — event_trader 처리 여부
  - `created_at` (DateTime)
- `backend/app/models/__init__.py`에 등록
- Alembic 마이그레이션

### 3.2 News 모델에 cluster_id 추가
- `backend/app/models/news.py`에 `cluster_id` (FK → news_clusters.id, nullable) 추가
- Alembic 마이그레이션

### 3.3 뉴스 클러스터링 서비스
- `backend/app/services/news_clustering.py` 생성
- `async def detect_news_clusters(db: AsyncSession, window_minutes: int = 60, min_count: int = 3) -> list[NewsCluster]`:
  - 최근 `window_minutes` 이내의 뉴스를 종목별로 그룹핑
  - 동일 종목 뉴스가 `min_count`건 이상이면 클러스터 생성
  - 이미 존재하는 클러스터와 겹치면 업데이트 (news_count, last_news_at)
  - 새 클러스터 발생 시 Redis 알림: `event:news_cluster:new` (List, RPUSH cluster_id)
- `async def get_unprocessed_clusters(db, stock_codes=None, limit=10) -> list[NewsCluster]`
- `async def mark_cluster_processed(db, cluster_id: int)`

### 3.4 뉴스 수집 파이프라인에 클러스터링 통합
- `backend/app/services/news_collector.py` 수정:
  - 뉴스 수집 완료 후 `detect_news_clusters()` 호출
  - 수집 루프의 기존 흐름: 뉴스 수집 → (추가) 클러스터 감지

### 3.5 클러스터링 파라미터 시스템 파라미터화
- `news_cluster_window_minutes` (기본 60) — 클러스터 감지 시간 윈도우
- `news_cluster_min_count` (기본 3) — 최소 뉴스 건수

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_news_clustering.py` — 종목별 뉴스 그룹핑 정상 동작 (3건 이상 → 클러스터 생성)
- [ ] `backend/tests/test_news_clustering.py` — 시간 윈도우 밖 뉴스는 클러스터에 포함되지 않음
- [ ] `backend/tests/test_news_clustering.py` — 기존 클러스터 업데이트 (중복 생성 방지)
- [ ] `backend/tests/test_news_clustering.py` — get_unprocessed_clusters / mark_cluster_processed 동작

### 수동 검증
- [ ] `uv run alembic upgrade head` 성공
- [ ] `uv run alt news collect` 실행 후 클러스터 생성 확인 (뉴스가 충분한 경우)

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_news_clustering.py -v`

## 참고사항
- 클러스터링은 단순 건수 기반으로 시작 (LLM 기반 의미 클러스터링은 후순위)
- 테마 기반 클러스터링(예: "반도체" 관련 여러 종목 뉴스)은 Phase 3에서 추가 고려
- 이 데이터는 Task 05(이벤트 감지)에서 사용됨
