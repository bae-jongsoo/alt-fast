# 서비스 레이어 패턴 정리

## 개요

- 프레임워크: FastAPI (async)
- ORM 세션: SQLAlchemy `AsyncSession`
- DI 패턴: FastAPI `Depends(get_db)`
- LLM: Gemini (OpenAI 호환 API)
- 알림: Telegram Bot API
- 실시간 데이터: KIS WebSocket → Redis → DB

---

## 디렉토리 구조

```
backend/app/
├── models/         # SQLAlchemy ORM 모델
├── schemas/        # Pydantic 응답 스키마
├── api/            # FastAPI 라우터 (얇은 레이어)
├── services/       # 비즈니스 로직
├── shared/         # 외부 API 클라이언트, 유틸리티
├── config.py       # pydantic-settings 기반 설정
├── database.py     # 엔진, 세션 팩토리, Base
├── main.py         # FastAPI app 생성
├── cli.py          # Typer CLI
└── logging_config.py
```

---

## 서비스 패턴

### 1. API 서비스 (db 주입 패턴)

**예시:** `services/dashboard.py`, `services/trades.py`, `services/chart.py`

```python
async def get_dashboard(db: AsyncSession) -> DashboardResponse:
    summary = await _get_summary(db)
    holdings = await _get_holdings(db)
    ...
    return DashboardResponse(summary=summary, holdings=holdings, ...)
```

**패턴:**
- `AsyncSession`을 인자로 받음
- 내부에서 `select()` 쿼리 실행
- Pydantic 스키마로 변환하여 반환
- 트랜잭션 관리는 호출자(API 레이어)에 위임

**API 레이어 (라우터):**
```python
@router.get("", response_model=DashboardResponse)
async def dashboard(db: AsyncSession = Depends(get_db)):
    return await get_dashboard(db)
```

### 2. 백그라운드/CLI 서비스 (세션 자체 관리 패턴)

**예시:** `services/daily_review.py`

```python
async def fetch_daily_bundle(target_date: datetime) -> dict:
    async with async_session() as session:
        # 쿼리 실행
        ...
    return bundle
```

**패턴:**
- `async_session()`을 직접 import하여 context manager로 사용
- CLI 커맨드에서 `asyncio.run(_run())`으로 호출
- API에서 호출되지 않는 독립 서비스

### 3. 수집기 서비스

**예시:** `services/market_collector.py`, `services/news_collector.py`, `services/dart_collector.py`

**패턴:**
- CLI에서 무한 루프로 주기적 실행
- `collect_*()` 함수가 한 번 수집 수행
- 결과를 `{"stock_codes": [...], "fetched_items": N, "saved_items": M}` 형태로 반환

### 4. 트레이더 서비스 (핵심 비즈니스 로직)

**파일:** `services/trader.py`

가장 복잡한 서비스. 전체 트레이딩 사이클을 관장.

**흐름:**
```
run_trading_cycle(db)
  ├─ get_open_position(db)     # 보유종목 확인
  ├─ build_buy/sell_prompt(db) # 프롬프트 조합
  │   ├─ _get_prompt_template(db, "buy"/"sell")  # DB에서 Jinja2 템플릿
  │   ├─ _build_stock_prompt_context(db, ...)     # 시장데이터 수집
  │   │   ├─ MarketSnapshot (최신 1건)
  │   │   ├─ DartDisclosure (7일 이내)
  │   │   ├─ News (useful=True/None, 최근 10건)
  │   │   ├─ build_candles() (Redis 틱 → 분봉)
  │   │   └─ Redis 호가 → OrderbookSnapshot 저장
  │   └─ Jinja2 렌더링
  ├─ ask_llm_by_level(level, prompt) # Gemini 호출
  ├─ parse_llm_json_object()         # 응답 파싱
  ├─ normalize_trade_decision()      # 정규화
  ├─ record_decision_history(db)     # DecisionHistory 저장
  ├─ execute_buy/sell(db)            # 가상 주문 실행
  │   ├─ apply_virtual_buy/sell()    # Asset 테이블 업데이트
  │   └─ OrderHistory 생성
  └─ db.commit()
```

### 5. 자산 관리 서비스

**파일:** `services/asset_manager.py`

**핵심 규칙:**
- 현금 자산: `stock_code IS NULL`, 정확히 1행
- 보유 종목: `stock_code IS NOT NULL`, **최대 1종목**
- 가상 매수: 현금 차감 (수수료 포함) + 포지션 생성
- 가상 매도: 현금 증가 (수수료+거래세 차감) + 포지션 삭제

**수수료 체계:**
```python
COMMISSION_RATE = 0.00015      # 0.015% (매수/매도 각각)
TRANSACTION_TAX_RATE = 0.002   # 0.2% (매도만)
```

### 6. 분봉 보충 서비스

**파일:** `services/candle_backfill.py`

**용도:** 장 마감 후 WebSocket으로 못 받은 빈 분봉을 KIS REST API로 보충
**스케줄:** 매일 15:40 자동 실행 (CLI `alt backfill candles-scheduler`)

---

## shared 모듈

| 모듈 | 역할 |
|------|------|
| `shared/kis.py` | KIS REST API 클라이언트 |
| `shared/kis_ws.py` | KIS WebSocket 클라이언트 |
| `shared/llm.py` | Gemini LLM 호출 (ask_llm_by_level) |
| `shared/telegram.py` | 텔레그램 메시지 전송 |
| `shared/naver_news.py` | 네이버 뉴스 검색 API |
| `shared/dart_api.py` | DART 공시 API |
| `shared/web_content.py` | 웹 페이지 본문 추출 |
| `shared/json_helpers.py` | LLM JSON 파싱/정규화 |

---

## 데이터 흐름 요약

### 매매 주문 생성 흐름

```
CLI: alt trader run
  → trader.run_trading_cycle(db)
    → 포지션 확인 → 프롬프트 생성 → LLM 호출 → 응답 파싱
    → DecisionHistory 저장
    → BUY/SELL → execute_buy/sell()
      → Asset 업데이트 (현금 차감/증가)
      → OrderHistory 생성
    → commit
```

### 분봉 데이터 수집 흐름

```
경로 1 (실시간):
  CLI: alt ws subscribe
    → KIS WebSocket 체결 틱 → Redis sorted set
    → trader 사이클 시 build_candles() → Redis 틱 → MinuteCandle DB 저장

경로 2 (보충):
  CLI: alt backfill candles
    → KIS REST API (당일분봉조회) → MinuteCandle DB 저장
```

### 호가 데이터 수집 흐름

```
CLI: alt ws subscribe
  → KIS WebSocket 호가 틱 → Redis sorted set (ws:quote:{code})
  → trader 사이클 시 Redis 최신 호가 → OrderbookSnapshot DB 저장
```
