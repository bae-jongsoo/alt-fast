# Task 04: 히스토리컬 데이터 백필

## 목표
향후 백테스트를 위해 과거 데이터를 수집한다: DART 공시 1년, 분봉 6개월, 뉴스 6개월, 매크로(미장/환율) 1년. 백그라운드에서 점진적으로 수집하는 CLI 명령어를 추가한다.

## 선행 조건
- Task 01 완료 (MacroSnapshot 모델)
- Task 03 완료 (News 모델 변경 반영)

## 구현 상세

### 4.1 매크로 데이터 백필
- `backend/app/shared/macro_api.py`에 `fetch_macro_data_range(start_date, end_date)` 추가
  - yfinance `download(period)` 대신 `download(start, end)` 사용
  - 일별 데이터를 MacroSnapshot으로 변환
- `backend/app/services/macro_collector.py`에 `async def backfill_macro(db, start_date, end_date)` 추가
  - 이미 존재하는 날짜는 스킵 (upsert)
  - 진행상황 로깅 (N/M일 완료)

### 4.2 DART 공시 백필
- `backend/app/services/dart_collector.py`에 `async def backfill_dart(db, start_date, end_date, stock_codes)` 추가
  - DART API의 날짜 범위 조회 활용
  - 일별 또는 주별로 나누어 수집 (API 제한 고려)
  - 이미 존재하는 공시 스킵

### 4.3 뉴스 백필
- `backend/app/services/news_collector.py`에 `async def backfill_news(db, start_date, end_date, stock_codes)` 추가
  - 네이버 뉴스 검색 API의 날짜 범위 파라미터 활용
  - 페이지네이션 처리 (최대 1000건/종목)
  - Rate limiting (초당 10건 제한 준수)

### 4.4 분봉 백필 강화
- 기존 `candle_backfill.py`에 기간 지정 백필 기능 추가 (또는 기존 기능 활용)
- KIS API 분봉 조회는 최대 30일이므로 일별로 반복 호출

### 4.5 통합 CLI 명령어
- `backend/app/cli.py`에 `backfill` 그룹 확장:
  - `alt backfill macro --start 2025-03-29 --end 2026-03-29` — 매크로 백필
  - `alt backfill dart --start 2025-03-29 --end 2026-03-29` — DART 백필
  - `alt backfill news --start 2025-09-29 --end 2026-03-29` — 뉴스 백필
  - `alt backfill all --macro-months 12 --dart-months 12 --news-months 6 --candle-months 6` — 전체 백필
- 각 명령어는 `--dry-run` 옵션 지원 (수집 대상 건수만 출력)
- 진행상황을 stdout에 출력 (tqdm 또는 간단한 카운터)

### 4.6 백필 상태 추적
- `system_parameter`에 백필 진행 상태 저장 (예: `backfill_macro_last_date`)
- 중단 후 재시작 시 마지막 진행 시점부터 이어서 수집

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_backfill.py` — backfill_macro() 테스트 (yfinance mock, 기간별 데이터 적재 확인)
- [ ] `backend/tests/test_backfill.py` — 중복 데이터 스킵 확인 (upsert 동작)
- [ ] `backend/tests/test_backfill.py` — 중단/재시작 시 이어서 수집 확인

### 수동 검증
- [ ] `uv run alt backfill macro --start 2026-03-01 --end 2026-03-28 --dry-run` — 대상 건수 출력
- [ ] `uv run alt backfill macro --start 2026-03-01 --end 2026-03-28` — 실제 수집 후 DB 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_backfill.py -v`

## 참고사항
- 백필은 서비스 운영에 영향을 주지 않도록 rate limiting 적용
- yfinance는 한번에 최대 2년 데이터 조회 가능, DART API는 일 요청 제한 있음
- 이 데이터는 향후 백테스트 프레임워크에서 사용 (현재 Phase에서는 직접 사용하지 않음)
- 장시간 소요되므로 supervisord 등록 없이 수동 CLI 실행 권장
