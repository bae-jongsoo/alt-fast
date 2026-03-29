# ALT — Auto-trading with LLM for Trading

LLM 기반 한국 주식 자동매매 시스템. 실시간 시세, 뉴스, 공시 데이터를 수집하고 LLM이 매매 판단을 내리는 가상(페이퍼) 트레이딩 플랫폼.

**Live**: https://alt.jscraft.work

---

## 데이터 모델

### 핵심 엔티티

```
Strategy (전략)
 ├── TargetStock (대상 종목)        — 전략별 감시 종목 목록
 ├── PromptTemplate (프롬프트)      — 전략별 buy/sell Jinja2 템플릿
 ├── Asset (자산)                   — 현금 + 보유 종목 (전략별 1종목 제한)
 ├── DecisionHistory (판단 이력)    — LLM 요청/응답/파싱 결과 전체 기록
 └── OrderHistory (주문 이력)       — 가상 매수/매도 + 손익 계산
```

### 시장 데이터

| 모델 | 설명 | 수집 방식 |
|------|------|-----------|
| `MarketSnapshot` | PER, PBR, EPS, 시가총액, 52주 고저, 외인/프로그램 매매 | KIS REST API, 장중 주기적 |
| `MinuteCandle` | 1분봉 OHLCV | KIS WebSocket → Redis → DB 변환 |
| `OrderbookSnapshot` | 호가 5단계 (매수/매도 가격·수량) | 매매 판단 시점에 저장 |
| `News` | 네이버 뉴스 (LLM 요약, useful 필터링) | 주기적 수집 |
| `DartDisclosure` | DART 공시 (최근 7일) | 주기적 수집 |

### ER 관계

```
Strategy 1──N TargetStock
Strategy 1──N PromptTemplate        (buy/sell 각 1개 활성, 버전 관리)
Strategy 1──N Asset                 (현금 1 + 보유종목 0~1)
Strategy 1──N DecisionHistory
Strategy 1──N OrderHistory
DecisionHistory 1──0..1 OrderHistory
OrderHistory(SELL).buy_order_id ──→ OrderHistory(BUY)
```

---

## LLM 매매 전략

### 트레이딩 사이클

매 사이클마다 하나의 Strategy에 대해 실행된다. (`trader.py: run_trading_cycle`)

```
1. 포지션 확인
   ├── 보유 종목 있음 → SELL 판단 모드
   └── 보유 종목 없음 → BUY 판단 모드

2. 종목별 데이터 수집
   ├── MarketSnapshot — 밸류에이션 (PER, PBR, EPS, BPS, 시총, 52주 고저)
   ├── MinuteCandle — 최근 30분봉 (Redis 틱 → 분봉 변환)
   ├── OrderbookSnapshot — 실시간 호가 5단계
   ├── News — 최근 뉴스 10건 (useful 필터)
   ├── DartDisclosure — 최근 7일 공시
   └── OrderHistory — 오늘 해당 종목 매매 이력 + 매수 사유

3. 프롬프트 조합
   ├── DB에서 활성 PromptTemplate 로드 (가장 높은 버전)
   ├── 수집 데이터를 <stock-info> XML 블록으로 구조화
   └── Jinja2 변수 바인딩 (현금, 오늘 성적, 보유 정보 등)

4. LLM 호출
   ├── DB 파라미터(llm_trading)로 레벨 결정 (normal / high)
   ├── normal → openclaw (GPT-5.2급)
   ├── high → nanobot (GPT-5.4급)
   └── 실패 시 최대 3회 재시도 (지수 백오프: 2s → 4s → 8s)

5. 응답 파싱 + 정규화
   ├── JSON 객체 추출 (parse_llm_json_object)
   ├── decision 정규화 (normalize_trade_decision)
   ├── BUY/SELL인데 price/quantity 누락 → HOLD로 다운그레이드
   └── 허용값: BUY, SELL, HOLD

6. 가상 주문 실행
   ├── BUY → 현금 차감, 포지션 생성
   ├── SELL → 포지션 청산, 현금 증가, 손익 계산
   └── 에러 시 텔레그램 알림
```

### 프롬프트 구조

프롬프트 템플릿은 DB(`prompt_templates`)에 저장되며, 웹 UI에서 실시간 수정 가능하다.
전략별로 `buy`/`sell` 타입 각각 버전 관리되며, 가장 높은 버전의 활성 템플릿이 사용된다.

**BUY 프롬프트 변수:**

| 변수 | 내용 |
|------|------|
| `current_time` | 현재 시각 (ISO 8601) |
| `cash_amount` | 보유 현금 |
| `today_performance` | 오늘 매매 성적 (승/패/무, 실현 손익) |
| `stock_infos` | 종목별 `<stock-info>` 블록 리스트 |

**SELL 프롬프트 추가 변수:**

| 변수 | 내용 |
|------|------|
| `quantity`, `avg_buy_price` | 보유 수량, 평균 매수가 |
| `breakeven_price` | 손익분기가 (수수료·세금 포함) |
| `profit_rate_net` | 현재 세후 수익률 (%) |
| `buy_target_pct` / `buy_stop_pct` | 매수 시 설정한 목표/손절 비율 |
| `buy_reason` | 매수 당시 LLM이 제시한 근거 |

**`<stock-info>` 블록 (LLM에 전달되는 종목 데이터):**

```json
{
  "stock_code": "005930",
  "stock_name": "삼성전자",
  "fundamental": { "per": 12.5, "pbr": 1.1, "eps": 5800, "bps": 52000, "hts_avls": "430조", "w52_hgpr": 88000, "w52_lwpr": 59000 },
  "disclosures": [{ "title": "사업보고서", "description": "...", "published_at": "2026-03-25T09:00:00" }],
  "news": [{ "title": "삼성전자 HBM 수주...", "summary": "...", "useful": true, "published_at": "..." }],
  "candles": [{ "minute_at": "...", "open": 71000, "high": 71500, "low": 70800, "close": 71200, "volume": 15000 }],
  "orderbook": { "asks": [{"price": 71300, "volume": 5000}], "bids": [{"price": 71200, "volume": 3000}] },
  "today_trades": [{ "buy_price": 70500, "sell_price": 71200, "profit_rate_net": 0.77 }]
}
```

### LLM 응답 포맷

LLM은 아래 JSON 구조로 응답해야 한다. 시스템이 자동 파싱 후 정규화한다.

```json
{
  "analysis": [
    {
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "reason": "단기 기술적 반등 구간 + 외인 순매수 전환"
    }
  ],
  "decision": {
    "result": "BUY",
    "stock_code": "005930",
    "price": 71500,
    "quantity": 10,
    "target_return_pct": 2.5,
    "stop_pct": -1.5
  }
}
```

- `result`: `BUY` / `SELL` / `HOLD`
- `price`, `quantity`: BUY/SELL 시 필수 (누락 시 HOLD로 다운그레이드)
- `target_return_pct`, `stop_pct`: 매수 시 설정, 이후 매도 판단에 활용

### 멀티 전략

하나의 시스템에서 여러 전략을 동시에 운영할 수 있다.

- 각 전략은 독립된 초기 자본(`initial_capital`), 대상 종목, 프롬프트를 보유
- 전략별로 동시에 1종목만 보유 가능 (포지션 제한)
- 전략 활성/비활성 전환은 웹 UI에서 가능

### 가상 매매 손익 계산

```
매수 비용 = 매수가 × 수량
매도 수익 = 매도가 × 수량
총 수수료 = (매수비용 × 0.015%) + (매도수익 × 0.015%) + (매도수익 × 0.2%)
세후 손익 = (매도수익 - 매수비용) - 총 수수료
세후 수익률 = 세후 손익 / 매수비용 × 100
```

> 수수료율 0.015% (매수+매도 각각), 거래세 0.2% (매도, KOSPI 기준)

---

## 데이터 파이프라인

```
KIS WebSocket ──→ Redis (sorted set, 종목별 틱) ──→ 1분봉 OHLCV (DB)
KIS REST API  ──→ MarketSnapshot (DB)
네이버 뉴스   ──→ LLM 요약 ──→ News (DB)
DART API      ──→ DartDisclosure (DB)

                 ┌──────────────────────────────────────┐
                 │           Trader 서비스               │
                 │  데이터 조합 → Jinja2 프롬프트 렌더링 │
                 │  → LLM 호출 → JSON 파싱 + 정규화     │
                 │  → 가상 주문 실행 → 텔레그램 알림     │
                 └──────────────────────────────────────┘
```

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Jinja2 |
| 프론트엔드 | React, TypeScript, Vite, TanStack Query, shadcn/ui |
| 데이터베이스 | PostgreSQL (asyncpg), Redis (실시간 틱 버퍼) |
| LLM | openclaw / nanobot (외부 CLI), OpenAI SDK 호환 (챗봇) |
| 인프라 | supervisor, nginx, Cloudflare Tunnel, GitHub webhook 자동 배포 |
| 외부 API | 한국투자증권(KIS), 네이버 뉴스, DART 공시, Telegram |

---

## 실행

```bash
# 백엔드
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 프론트엔드
cd frontend && npm install && npm run dev

# CLI
alt trader run                      # 매매 판단 루프
alt market collect                  # 시장 스냅샷 수집
alt news collect                    # 뉴스 수집
alt dart collect                    # 공시 수집
alt ws subscribe                    # 실시간 체결 WebSocket
alt backfill candles-scheduler      # 분봉 빈구간 보충
alt review daily                    # 일일 리뷰 생성

# 전체 서비스 (supervisor)
make restart && make status
```
