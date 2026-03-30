# Task 01: 매크로 데이터 수집기 (macro_collector)

## 목표
미장 지수, 아시아 지수, 환율, 금리(만기별), 변동성, 원자재, 반도체지수 등 거시경제 데이터를 수집하여 DB에 적재하는 새 프로세스를 추가한다. 장 시작 전(08:30) 수집하여 event_trader의 매매 판단 프롬프트에 포함할 수 있도록 한다.

## 선행 조건
- 없음 (기존 프로젝트 상태에서 시작)

## 구현 상세

### 1.1 MacroSnapshot 모델 생성
- `backend/app/models/macro_snapshot.py` 생성
- 필드:
  - `id` (PK, Integer)
  - `snapshot_date` (Date, unique) — 수집 날짜
  - **미국 지수**
  - `sp500_close` (Numeric, nullable)
  - `sp500_change_pct` (Numeric, nullable)
  - `nasdaq_close` (Numeric, nullable)
  - `nasdaq_change_pct` (Numeric, nullable)
  - `dow_close` (Numeric, nullable)
  - `dow_change_pct` (Numeric, nullable)
  - `russell2000_close` (Numeric, nullable)
  - `russell2000_change_pct` (Numeric, nullable)
  - **변동성**
  - `vix` (Numeric, nullable)
  - `vix_change_pct` (Numeric, nullable)
  - **미국 금리**
  - `us_13w_tbill` (Numeric, nullable) — 13주 단기
  - `us_5y_treasury` (Numeric, nullable)
  - `us_10y_treasury` (Numeric, nullable)
  - `us_30y_treasury` (Numeric, nullable)
  - **환율**
  - `usd_krw` (Numeric, nullable)
  - `usd_krw_change_pct` (Numeric, nullable)
  - `usd_cny` (Numeric, nullable)
  - `usd_cny_change_pct` (Numeric, nullable)
  - `usd_jpy` (Numeric, nullable)
  - `usd_jpy_change_pct` (Numeric, nullable)
  - `dxy` (Numeric, nullable) — 달러 인덱스
  - `dxy_change_pct` (Numeric, nullable)
  - **원자재**
  - `gold` (Numeric, nullable)
  - `gold_change_pct` (Numeric, nullable)
  - `wti` (Numeric, nullable)
  - `wti_change_pct` (Numeric, nullable)
  - `copper` (Numeric, nullable)
  - `copper_change_pct` (Numeric, nullable)
  - **아시아 지수**
  - `nikkei_close` (Numeric, nullable)
  - `nikkei_change_pct` (Numeric, nullable)
  - `hang_seng_close` (Numeric, nullable)
  - `hang_seng_change_pct` (Numeric, nullable)
  - `shanghai_close` (Numeric, nullable)
  - `shanghai_change_pct` (Numeric, nullable)
  - **반도체/한국 관련**
  - `sox_close` (Numeric, nullable) — 필라델피아 반도체지수
  - `sox_change_pct` (Numeric, nullable)
  - `ewy_close` (Numeric, nullable) — MSCI Korea ETF
  - `ewy_change_pct` (Numeric, nullable)
  - `kr_bond_10y_close` (Numeric, nullable) — KOSEF 국고채10년
  - `kr_bond_10y_change_pct` (Numeric, nullable)
  - **한국 기준금리**
  - `kr_base_rate` (Numeric, nullable) — SystemParameter에서 읽어 채움 (연 8회 변동)
  - **기타**
  - `raw_data` (JSON, nullable) — yfinance 원본 응답 전체 (디버깅용)
  - `created_at` (DateTime)
- 모든 지표 컬럼은 nullable — 개별 티커 수집 실패해도 나머지는 저장
- `backend/app/models/__init__.py`에 등록

### 1.2 Alembic 마이그레이션
- `uv run alembic revision --autogenerate -m "add macro_snapshots table"` 실행
- 마이그레이션 파일 검증 후 `uv run alembic upgrade head`

### 1.3 매크로 데이터 수집 모듈
- `backend/app/shared/macro_api.py` 생성
- **데이터 소스:** Yahoo Finance (yfinance 패키지, 무료, API 키 불필요)

#### yfinance 티커 전체 목록

| 카테고리 | 티커 | 설명 |
|---------|------|------|
| **미국 지수** | `^GSPC` | S&P 500 |
| | `^IXIC` | NASDAQ |
| | `^DJI` | Dow Jones |
| | `^RUT` | Russell 2000 (소형주) |
| **변동성** | `^VIX` | VIX (공포지수) |
| **미국 금리** | `^IRX` | 13주 T-Bill (단기) |
| | `^FVX` | 5년 국채 |
| | `^TNX` | 10년 국채 |
| | `^TYX` | 30년 국채 |
| **환율** | `USDKRW=X` | 원/달러 |
| | `USDCNY=X` | 위안/달러 |
| | `USDJPY=X` | 엔/달러 |
| | `DX-Y.NYB` | 달러 인덱스 (DXY) |
| **원자재** | `GC=F` | 금 |
| | `CL=F` | 원유 (WTI) |
| | `HG=F` | 구리 (경기 선행지표) |
| **아시아 지수** | `^N225` | 니케이 225 |
| | `^HSI` | 항셍 |
| | `000001.SS` | 상해종합 |
| **반도체/한국** | `^SOX` | 필라델피아 반도체지수 |
| | `EWY` | iShares MSCI Korea ETF |
| | `138230.KS` | KOSEF 국고채10년 |

- **총 20개 티커**, `yf.download()` 한 번에 배치 호출 (개별 Ticker 호출보다 빠름)
- **한국 기준금리:** SystemParameter `kr_base_rate`에서 읽음 (변동 빈도 극히 낮아 수동 관리)
- 함수: `async def fetch_macro_data(date: date | None = None) -> MacroData` (Pydantic 모델 반환)
- yfinance는 동기 라이브러리이므로 `asyncio.to_thread()`로 래핑
- 에러 시 개별 필드 None 허용 (부분 실패 허용)
- 등락률은 전일 대비 자동 계산

### 1.4 매크로 수집 서비스
- `backend/app/services/macro_collector.py` 생성
- `async def collect_macro_snapshot(db: AsyncSession) -> MacroSnapshot`:
  - `fetch_macro_data()` 호출
  - DB upsert (snapshot_date 기준, 이미 있으면 업데이트)
  - 수집 결과 로깅
- `async def run_macro_collector()`:
  - 장 전 08:30에 1회 수집
  - 이후 장중 12:00에 1회 업데이트 (환율 변동 반영)
  - 시간 체크 루프, 수집 완료 시 다음 시간까지 sleep

### 1.5 CLI 명령어 추가
- `backend/app/cli.py`에 `macro` 커맨드 그룹 추가
- `alt macro collect` — 즉시 1회 수집
- `alt macro collect-scheduler` — 스케줄러 모드 (08:30, 12:00)

### 1.6 API 엔드포인트 (선택)
- `backend/app/api/macro.py` — `GET /api/macro/latest` (최신 매크로 스냅샷 조회)
- 라우터 등록

### 1.7 의존성 추가
- `pyproject.toml`에 `yfinance` 추가
- `uv sync`

### 1.8 supervisord 등록
- `supervisord.conf`에 `macro` 프로세스 추가
- `collectors` 그룹에 포함

## 완료 기준

### 자동 검증 (테스트)
- [ ] `backend/tests/test_macro_collector.py` — MacroSnapshot 모델 CRUD 테스트 (생성, 조회, upsert)
- [ ] `backend/tests/test_macro_collector.py` — fetch_macro_data() 모킹 테스트 (정상 응답, 부분 실패)
- [ ] `backend/tests/test_macro_collector.py` — collect_macro_snapshot() 서비스 테스트 (DB 적재 확인)

### 수동 검증
- [ ] `uv run alembic upgrade head` 성공
- [ ] `uv run alt macro collect` 실행 시 DB에 데이터 적재 확인
- [ ] `curl localhost:8000/api/macro/latest` 응답 확인

**검증 실행 명령어**: `cd backend && uv run pytest tests/test_macro_collector.py -v`

## 참고사항
- yfinance는 장 종료 후 데이터가 확정되므로, 한국 장 전(08:30)에 수집하면 전일 미장 데이터를 안정적으로 가져올 수 있음
- `yf.download(tickers=[...], period="2d")`로 20개 티커 배치 호출 → 개별 호출 대비 훨씬 빠름
- 한국 기준금리는 변동 빈도가 매우 낮으므로(연 8회 금통위 결정) SystemParameter `kr_base_rate`에 수동 입력 (현재 2.75%, 2025.11 인하)
- 이 데이터는 Phase 2의 event_trader 프롬프트에서 사용됨
- 장단기 금리 스프레드(10y - 13w)는 경기침체 시그널로 활용 가능 — 프롬프트에 파생 지표로 포함 권장
