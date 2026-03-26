# API / CLI 구조 정리

## API 엔드포인트

**프레임워크:** FastAPI
**베이스:** `app/main.py` → `app/api/router.py`

### 라우터 등록 구조

```python
# app/api/router.py
router = APIRouter()
router.include_router(auth_router)       # /api/auth
router.include_router(chart_router)      # /api/chart
router.include_router(chatbot_router)    # /api/chatbot
router.include_router(dashboard_router)  # /api/dashboard
router.include_router(trades_router)     # /api/trades
router.include_router(news_router)       # /api/news
router.include_router(settings_router)   # /api/settings
router.include_router(deploy_router)     # /api/deploy
```

### 엔드포인트 상세

| Method | Path | 설명 | 서비스 |
|--------|------|------|--------|
| GET | `/api/health` | 헬스체크 | (inline) |
| GET | `/api/dashboard` | 대시보드 데이터 | `services/dashboard.py` |
| GET | `/api/trades/orders` | 주문 이력 (페이징, 필터) | `services/trades.py` |
| GET | `/api/trades/decisions` | LLM 판단 이력 (페이징, 필터) | `services/trades.py` |
| GET | `/api/trades/decisions/{id}` | 판단 상세 (프롬프트/응답 포함) | `services/trades.py` |
| GET | `/api/chart/candles` | 분봉 차트 데이터 | `services/chart.py` |
| - | `/api/auth/*` | 로그인/인증 | `services/auth.py` |
| - | `/api/news/*` | 뉴스 조회 | `services/news.py` |
| - | `/api/settings/*` | 시스템 설정 CRUD | `services/settings.py` |
| - | `/api/chatbot/*` | 챗봇 | `services/chatbot.py` |
| - | `/api/deploy/*` | 배포 웹훅 | - |

### API 패턴

```python
# app/api/trades.py (대표적인 패턴)
router = APIRouter(prefix="/api/trades", tags=["trades"])

@router.get("/orders", response_model=OrderHistoryListResponse)
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    order_type: str | None = None,
    stock_code: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_orders(db, page, page_size, start_date, end_date, order_type, stock_code)
```

**보고서 API를 추가할 때:**
- `app/api/report.py` 생성
- `APIRouter(prefix="/api/reports", tags=["reports"])`
- `app/api/router.py`에 `include_router` 추가

---

## CLI 구조

**프레임워크:** Typer
**엔트리포인트:** `app/cli.py` → `pyproject.toml`의 `alt` 스크립트

### 커맨드 그룹

```
alt
├── trader
│   └── run          # 트레이딩 사이클 반복 실행
├── market
│   └── collect      # 시장 스냅샷 수집 반복
├── news
│   └── collect      # 뉴스 수집 반복
├── dart
│   └── collect      # DART 공시 수집 반복
├── ws
│   └── subscribe    # KIS WebSocket 실시간 구독
├── todo
│   └── list         # TODO 목록 조회
├── db
│   └── migrate      # Alembic 마이그레이션
├── backfill
│   ├── candles           # 분봉 보충 (수동)
│   └── candles-scheduler # 분봉 보충 스케줄러 (15:40 자동)
└── review
    └── daily        # 일일 LLM 회고 생성 + 텔레그램
```

### CLI 패턴

```python
# 서브커맨드 그룹 생성
review_app = typer.Typer(help="일일 회고/리포트")
app.add_typer(review_app, name="review")

# 커맨드 등록
@review_app.command("daily")
def review_daily(
    date: Optional[str] = typer.Option(None, "--date", help="대상 날짜 (YYYY-MM-DD)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="텔레그램 전송 없이 출력만"),
) -> None:
    async def _run() -> None:
        # 비동기 서비스 호출
        ...
    asyncio.run(_run())
```

**보고서 CLI를 추가할 때:**
- `review_app`에 새 커맨드 추가 (예: `alt review report --date 2026-03-26`)
- 또는 별도 `report_app` 그룹 생성

### 공통 유틸리티 (cli.py 내)

| 함수 | 용도 |
|------|------|
| `_parse_stock_codes(str)` | "005930,000660" → ["005930", "000660"] |
| `_get_system_param(session, key, default)` | SystemParameter 조회 |
| `_get_target_stock_codes(session)` | 활성 종목코드 목록 |
| `_is_market_open(start, end)` | 장 운영 시간 체크 |

---

## Pydantic 스키마 패턴

**디렉토리:** `app/schemas/`

```python
# 응답 아이템
class OrderHistoryItem(BaseModel):
    id: int
    created_at: datetime
    stock_code: str
    ...

# 리스트 응답 (페이징)
class OrderHistoryListResponse(BaseModel):
    items: list[OrderHistoryItem]
    total: int
    page: int
    page_size: int
```

**보고서 스키마를 추가할 때:**
- `app/schemas/report.py` 생성
- 각 분석 항목별 Pydantic 모델 정의

---

## 설정 / 환경

**파일:** `app/config.py`

pydantic-settings 기반. `.env` 파일에서 로드.

| 설정 | 용도 |
|------|------|
| DATABASE_URL | PostgreSQL (asyncpg) |
| REDIS_URL | Redis (틱 데이터 버퍼) |
| KIS_APP_KEY/SECRET | 한국투자증권 API |
| GEMINI_API_KEY | LLM |
| TELEGRAM_BOT_TOKEN/CHAT_ID | 알림 |

---

## 프로세스 구성 (supervisord.conf)

시스템은 다수의 프로세스로 구성:
- `web`: FastAPI 서버 (uvicorn)
- `trader`: 트레이딩 사이클 (`alt trader run`)
- `market`: 시장 스냅샷 수집 (`alt market collect`)
- `news`: 뉴스 수집 (`alt news collect`)
- `dart`: DART 수집 (`alt dart collect`)
- `ws`: WebSocket 구독 (`alt ws subscribe`)
- `backfill`: 분봉 보충 스케줄러 (`alt backfill candles-scheduler`)
