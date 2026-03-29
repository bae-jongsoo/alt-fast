8으# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ALT (Auto-trading with LLM for Trading) — LLM 기반 한국 주식 자동매매 시스템. FastAPI 백엔드 + React 프론트엔드 모놀리스로, Mac Mini에서 supervisor로 여러 백그라운드 서비스를 운영한다. 실시간 시세(KIS WebSocket → Redis → 분봉), 뉴스/공시 수집, Gemini LLM 매매 판단, 가상(페이퍼) 트레이딩을 수행한다.

## Common Commands

### Backend (working directory: `backend/`)
```bash
uv sync                              # 의존성 설치
uv run alembic upgrade head          # DB 마이그레이션
uv run pytest                        # 전체 테스트
uv run pytest tests/test_trades.py   # 단일 테스트 파일
uv run pytest -k test_name           # 특정 테스트
uv run uvicorn app.main:app --reload # 개발 서버 (port 8000)
```

### Frontend (working directory: `frontend/`)
```bash
npm install         # 의존성 설치
npm run dev         # Vite 개발 서버 (port 5173, /api → localhost:8000 프록시)
npm run build       # tsc + vite build (프로덕션)
npm run lint        # ESLint
```

### CLI (`alt` command, backend venv 활성화 상태)
```bash
alt trader run              # 매매 판단 루프
alt market collect          # 시장 스냅샷 수집
alt news collect            # 뉴스 수집
alt dart collect            # 공시 수집
alt ws subscribe            # KIS WebSocket 실시간 체결
alt backfill candles-scheduler  # 분봉 빈구간 보충
alt review daily            # 일일 리뷰 생성
```

### Makefile (프로젝트 루트)
```bash
make status             # supervisor 상태 확인
make restart            # 전체 서비스 재시작
make restart-api        # API 서버만 재시작
make restart-collectors # 수집기만 재시작
make log-api            # API 에러 로그 tail
make shell              # IPython 셸 (DB 세션 포함)
make db                 # PostgreSQL 접속
make deploy             # 수동 배포
```

## Architecture

### Backend (`backend/app/`)

**계층 구조:** API (routers) → Schemas (Pydantic) → Services (비즈니스 로직) → Models (SQLAlchemy ORM) → Database

- **`api/`** — FastAPI 라우터. `router.py`에서 모든 서브 라우터 결합.
- **`models/`** — SQLAlchemy 2.0 async ORM 모델 (12개 테이블). `asset`, `order_history`, `decision_history`, `minute_candle`, `news`, `dart_disclosure`, `prompt_template`, `target_stock`, `system_parameter` 등.
- **`schemas/`** — Pydantic v2 request/response 모델.
- **`services/`** — 핵심 비즈니스 로직. 주요 파일:
  - `trader.py` (875줄) — LLM 매매 판단 루프. 시장 데이터 수집 → 프롬프트 조합 → LLM 호출 → 주문 실행.
  - `chatbot.py` — Gemini function calling 기반 챗봇. SSE 스트리밍.
  - `ws_collector.py` — KIS WebSocket → Redis sorted set → 1분봉 생성.
  - `asset_manager.py` — 가상 포지션 관리.
- **`shared/`** — 외부 연동 유틸리티 (`kis.py`, `llm.py`, `telegram.py`, `naver_news.py`, `dart_api.py`).
- **`cli.py`** — Typer CLI. `alt` 명령어로 서비스 실행.
- **`config.py`** — Pydantic Settings. 모든 설정은 `.env`에서 로드.
- **`database.py`** — async SQLAlchemy engine, session factory.

### Frontend (`frontend/src/`)

- **`pages/`** — 7개 라우트: Dashboard, Trades, News, Chart, Settings, Chat, Login.
- **`components/`** — shadcn/ui 기반. `layout/`, `dashboard/`, `trades/`, `news/`, `settings/`, `chatbot/`, `ui/` 하위 구조.
- **`hooks/`** — `useAuth.ts` (JWT 인증 컨텍스트), `useFetch.ts` (데이터 페칭).
- **`lib/api.ts`** — axios 인스턴스. Authorization 헤더 자동 첨부.
- **상태 관리:** TanStack React Query (서버 상태, 30초 기본 stale), React Context (인증).

### Data Pipeline

```
KIS WebSocket → Redis (sorted set, 종목별) → 분봉 OHLCV (DB)
KIS REST API → 시장 스냅샷 (DB)
네이버 뉴스 → LLM 요약 → 뉴스 (DB)
DART API → 공시 (DB)
→ Trader 서비스: 데이터 조합 → Gemini 프롬프트 → 매수/매도/관망 판단 → 가상 주문
```

### Infrastructure

- **supervisor:** 7개 프로세스 관리 (api, news, market, dart, trader, ws, backfill-candles). `supervisord.conf` 참조.
- **nginx:** 리버스 프록시. 프론트엔드 정적 파일 + API 프록시.
- **배포:** GitHub webhook → `POST /api/deploy/webhook` → `scripts/deploy.sh` → git pull, uv sync, npm build, supervisor restart, Telegram 알림.
- **로그:** `/var/log/alt-fast/` 하위 서비스별 로그 파일.

## Key Technical Details

- **Async-first:** 모든 DB/네트워크 I/O는 비동기 (asyncpg, aioredis, httpx).
- **인증:** 단일 사용자 (ADMIN_ID/PW from .env), JWT 24시간, refresh token 없음.
- **DB 설정 관리:** 종목 목록(`target_stock`), 프롬프트 템플릿(`prompt_template`), 시스템 파라미터(`system_parameter`) 모두 DB에 저장하고 웹 UI에서 수정 가능.
- **가상 매매:** 실제 KIS 주문 없이 가상 포지션으로 P&L 추적. `profit_loss_net` (세후 실현손익) 컬럼 사용.
- **테스트 DB:** `alt_fast_test` (별도 PostgreSQL DB). `backend/tests/conftest.py`에서 async fixture 설정.
- **Alembic 마이그레이션:** `backend/alembic/versions/` 디렉토리. 새 마이그레이션은 `uv run alembic revision --autogenerate -m "description"`.
- **LLM:** Gemini 2.5-flash (openai SDK 호환). `shared/llm.py`의 `ask_llm_by_level` 함수.
