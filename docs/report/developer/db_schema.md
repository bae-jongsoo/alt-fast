# DB 스키마 정리

## 개요

- ORM: SQLAlchemy 2.x (async, mapped_column)
- DB: PostgreSQL (asyncpg)
- 마이그레이션: Alembic
- Base 클래스: `app.database.Base` (DeclarativeBase)
- 모든 모델: `backend/app/models/`

---

## 핵심 테이블 (보고서 구현에 직접 사용)

### 1. order_histories (OrderHistory)

**파일:** `app/models/order_history.py`

매수/매도 주문 기록. 보고서의 대부분의 분석이 이 테이블에서 시작된다.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| decision_history_id | int (FK → decision_histories.id, CASCADE) | 이 주문을 발생시킨 LLM 판단 |
| stock_code | String(32) | 종목코드 (예: "005930") |
| stock_name | String(50) | 종목명 |
| order_type | String(4) | **"BUY"** 또는 **"SELL"** |
| order_price | Numeric(20,2) | 주문가 |
| order_quantity | int | 주문수량 |
| order_total_amount | Numeric(20,2) | 주문총액 (price × qty) |
| result_price | Numeric(20,2) | 체결가 |
| result_quantity | int | 체결수량 |
| result_total_amount | Numeric(20,2) | 체결총액 |
| buy_order_id | int \| None (FK → order_histories.id, self-ref) | **SELL일 때** 매칭되는 BUY 주문 ID |
| profit_loss | Numeric(20,2) \| None | 세전 손익 (SELL만) |
| profit_rate | float \| None | 세전 수익률 % (SELL만) |
| profit_loss_net | Numeric(20,2) \| None | **세후 손익** (SELL만) |
| profit_rate_net | float \| None | **세후 수익률 %** (SELL만) |
| order_placed_at | datetime | 주문 시각 |
| result_executed_at | datetime \| None | 체결 시각 |
| created_at | datetime (server_default=now()) | 레코드 생성 시각 |

**인덱스:**
- `ix_order_histories_stock_code`
- `ix_order_histories_order_placed_at`
- `ix_order_histories_result_executed_at`
- `ix_order_histories_created_at`
- `ix_order_histories_stock_code_created_at`

**BUY-SELL 매칭 방법:**
- SELL 레코드의 `buy_order_id`로 직접 매칭 (1차)
- fallback: 같은 stock_code에서 BUY 이후 가장 가까운 SELL 매칭

**손익 계산 공식 (trader.py 참조):**
```
수수료율 = 0.015% (매수/매도 각각)
거래세 = 0.2% (매도만, KOSPI)
profit_loss = (sell_price - avg_buy_price) × quantity
total_fee = buy_cost × 0.00015 + sell_cost × 0.00015 + sell_cost × 0.002
profit_loss_net = profit_loss - total_fee
```

---

### 2. minute_candles (MinuteCandle)

**파일:** `app/models/minute_candle.py`

1분봉 데이터. 보유구간 고가/저가, 변동성 분석, Equity Curve에 사용.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| stock_code | String(6) | 종목코드 |
| minute_at | datetime | 분봉 시각 (분 단위, 초=0) |
| open | int | 시가 |
| high | int | 고가 |
| low | int | 저가 |
| close | int | 종가 |
| volume | int (BigInteger) | 거래량 |

**제약:**
- UniqueConstraint: (`stock_code`, `minute_at`)

**인덱스:**
- `ix_minute_candles_stock_code`
- `ix_minute_candles_minute_at`
- `ix_minute_candles_stock_code_minute_at`

**데이터 수집 경로 2가지:**
1. **실시간 (WebSocket):** `ws_collector.py` → Redis 틱 → `build_candles()` → DB
2. **보충 (REST API):** `candle_backfill.py` → KIS 당일분봉조회 API → DB

---

### 3. decision_histories (DecisionHistory)

**파일:** `app/models/decision_history.py`

LLM의 매 판단 기록. HOLD 복기, LLM 소스별 성과 분석에 필수.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| stock_code | String(6) | 판단 대상 종목 |
| stock_name | String(50) | 종목명 |
| decision | String(16) | **"BUY"**, **"SELL"**, **"HOLD"** |
| request_payload | Text \| None | LLM에 보낸 프롬프트 전문 |
| response_payload | Text \| None | LLM 응답 전문 |
| parsed_decision | JSON \| None | **파싱된 LLM 응답 (구조화)** |
| processing_time_ms | int | LLM 처리 시간 (ms) |
| is_error | bool | 오류 여부 |
| error_message | Text \| None | 오류 메시지 |
| created_at | datetime (server_default=now()) | 판단 시각 |

**인덱스:**
- `ix_decision_histories_decision`
- `ix_decision_histories_created_at`
- `ix_decision_histories_is_error_created_at`

**parsed_decision 구조 (JSON):**
```json
{
  "decision": {
    "result": "BUY",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "price": 72000,
    "quantity": 10,
    "target_return_pct": 2.0,
    "stop_pct": -1.5,
    "sources": [
      {"type": "기술적분석", "weight": 40, "detail": "..."},
      {"type": "뉴스", "weight": 30, "detail": "..."},
      {"type": "공시", "weight": 20, "detail": "..."},
      {"type": "수급", "weight": 10, "detail": "..."}
    ]
  },
  "analysis": [
    {
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "confidence": 75,
      "reason": "..."
    }
  ]
}
```

**보고서 7번(LLM 판단근거 복기)에서 사용하는 핵심 필드:** `parsed_decision.decision.sources`

---

### 4. orderbook_snapshots (OrderbookSnapshot)

**파일:** `app/models/orderbook_snapshot.py`

5호가 스냅샷. 보고서 11번(호가 수급 분석)에 사용.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| stock_code | String(6) | |
| snapshot_at | datetime | 스냅샷 시각 (분 단위) |
| ask_price1~5 | int | 매도호가 1~5 |
| ask_volume1~5 | int (BigInteger) | 매도잔량 1~5 |
| bid_price1~5 | int | 매수호가 1~5 |
| bid_volume1~5 | int (BigInteger) | 매수잔량 1~5 |
| total_ask_volume | int (BigInteger) \| None | 총 매도잔량 |
| total_bid_volume | int (BigInteger) \| None | 총 매수잔량 |

**제약:**
- UniqueConstraint: (`stock_code`, `snapshot_at`)

**데이터 수집:** `trader.py`의 `_build_stock_prompt_context()` 안에서 Redis 호가 틱 → DB merge

---

## 보조 테이블

### 5. assets (Asset)

**파일:** `app/models/asset.py`

현재 보유 자산 상태. 현금 + 보유종목.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| stock_code | String(32) \| None | **None이면 현금** |
| stock_name | String(50) \| None | |
| quantity | int | 보유수량 (현금은 1) |
| unit_price | Numeric(20,2) | 평균단가 (현금은 총액과 동일) |
| total_amount | Numeric(20,2) | 총액 |
| created_at | datetime | |
| updated_at | datetime | |

**규칙:** 동시에 보유 종목은 **1개만** 허용 (`get_open_position` 참조)

---

### 6. market_snapshots (MarketSnapshot)

**파일:** `app/models/market_snapshot.py`

종목 기본 정보 스냅샷 (PER/PBR/EPS, 52주 고저, 외국인 비율 등).

| 주요 컬럼 | 설명 |
|-----------|------|
| stock_code, stock_name | 종목 |
| external_id | 중복방지용 고유키 |
| per, pbr, eps, bps | 밸류에이션 |
| w52_hgpr, w52_lwpr | 52주 고/저가 |
| hts_frgn_ehrt, frgn_ntby_qty | 외국인 보유율/순매수 |
| vol_tnrt | 거래회전율 |
| vi_cls_code | VI 발동 코드 |

---

### 7. target_stocks (TargetStock)

**파일:** `app/models/target_stock.py`

매매 대상 종목 마스터.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | int (PK) | |
| stock_code | String(6), unique | |
| stock_name | String(50) | |
| dart_corp_code | String(8) \| None | DART 기업코드 |
| is_active | bool | 활성 여부 |
| created_at | datetime | |

---

### 8. news (News)

**파일:** `app/models/news.py`

네이버 뉴스. useful 필드로 유용한 뉴스 필터링.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| stock_code | String(32) | |
| external_id | String(128), unique | |
| title | String(255) | |
| summary | Text \| None | LLM 요약 |
| useful | bool \| None | 유용성 판단 결과 |
| published_at | datetime \| None | |

---

### 9. dart_disclosures (DartDisclosure)

**파일:** `app/models/dart_disclosure.py`

DART 공시.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| stock_code | String(32) | |
| corp_code | String(64) | DART 기업코드 |
| rcept_no | String(32) | 접수번호 |
| title | String(255) | |
| description | Text \| None | |
| published_at | datetime \| None | |

---

### 10. prompt_templates (PromptTemplate)

**파일:** `app/models/prompt_template.py`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| prompt_type | String(10) | "buy" 또는 "sell" |
| content | Text | Jinja2 템플릿 |
| version | int | 버전 |
| is_active | bool | 활성 여부 |

---

### 11. system_parameters (SystemParameter)

**파일:** `app/models/system_parameter.py`

시스템 설정값 (key-value).

| 주요 키 | 기본값 | 설명 |
|---------|--------|------|
| trading_interval | "60" | 트레이딩 사이클 간격(초) |
| market_start_time | "09:00" | 장 시작 |
| market_end_time | "15:30" | 장 종료 |
| market_snapshot_interval | "60" | 시장 스냅샷 수집 간격(초) |
| news_interval | "300" | 뉴스 수집 간격(초) |
| dart_interval | "600" | DART 수집 간격(초) |

---

### 12. todos (Todo)

**파일:** `app/models/todo.py`

TODO 관리 (보고서와 무관).

---

## 보고서 11개 항목별 데이터 가용성

| # | 분석 항목 | 필요 테이블 | 데이터 있음? | 비고 |
|---|----------|------------|-------------|------|
| 1 | 종목별 매매 타임라인 | order_histories | **O** | buy_order_id로 BUY-SELL 매칭 |
| 2 | 놓친 기회 분석 | order_histories + minute_candles | **O** | 보유구간 분봉의 high/low |
| 3 | 시간대별 수익 분석 | order_histories | **O** | result_executed_at 기준 그룹핑 |
| 4 | HOLD 판단 복기 | decision_histories + minute_candles | **O** | decision="HOLD" 건 + 이후 분봉 |
| 5 | 승률 / 손익비 | order_histories | **O** | SELL의 profit_loss, profit_loss_net |
| 6 | 변동성 대비 성과 | minute_candles + order_histories | **O** | 일중 high-low 범위 |
| 7 | LLM 판단근거 복기 | decision_histories + order_histories | **O** | parsed_decision.decision.sources |
| 8 | 코스피/코스닥 대비 수익률 | (없음, API 호출 필요) | **API** | KIS API로 당일 지수 종가 조회 |
| 9 | 동일종목 반복매매 | order_histories | **O** | 같은 stock_code 복수 BUY-SELL |
| 10 | 자산 변동 곡선 | minute_candles + order_histories | **O** | 시뮬레이션 계산 |
| 11 | 호가 수급 분석 | orderbook_snapshots + order_histories | **O** | 데이터 축적 중 |
