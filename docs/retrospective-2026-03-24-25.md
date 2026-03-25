# 회고: 2026-03-24 ~ 2026-03-25

## 매매 결과

### 3/24 (월)
- 42건 청산, 승14/패18/무10, 총 손익 **-8,900원**
- 버그 수정 전(~11:06): 17건, 승3, **-13,900원**
- 버그 수정 후(11:06~): 25건, 승11, **+5,000원**
- 핵심: 오전 버그 상태에서의 손실이 오후 수익을 상쇄

### 3/25 (화)
- 26건 청산, 승6/패19/무1, 총 손익 **+16,750원** (전일 이월 기아 +25,200원 포함)
- 이월분 제외 시 **-8,450원**
- 오전 수익 → 오후 하락장에서 반복 손절로 까먹음
- 카카오 13주 미청산 상태로 장 마감

## 발견 및 수정한 버그

### 치명적 버그
1. **sell 프롬프트 현재가 오류** — `candles[0]`(30분 전 가격)을 현재가로 사용. 사자마자 +0.62% 수익률이 뜨는 등 잘못된 매도 판단 유발 → `candles[-1]`로 수정
2. **분봉 거래량 오류** — pykis `response.volume`이 누적거래량(ACML_VOL)이었는데 이를 sum하여 분당 수십억주로 기록됨 → `CNTG_VOL`(체결 건별 수량)으로 수정
3. **volume 컬럼 int32 오버플로** — 삼성전자 거래량 21억이 int32 범위 초과하여 INSERT 실패 → 트레이딩 세션 전체 롤백 → BigInteger 마이그레이션
4. **pykis 호가 파싱 에러** — KIS API가 62개 필드를 보내지만 pykis는 59개만 기대하여 `Invalid data length: 62` 에러. 호가 데이터가 한 번도 수집된 적 없었음

### 배포 관련
5. **deploy.sh requirements.txt 오류** — `uv pip install -r requirements.txt`인데 실제로는 pyproject.toml + uv.lock 사용 → `uv sync`로 수정. 배포가 한동안 통째로 실패하고 있었음
6. **deploy.sh .env 경로 오류** — `backend/.env` → `.env` (프로젝트 루트)
7. **normalize_trade_decision에서 sources 유실** — decision dict를 새로 만들면서 sources, confidence 등 원본 필드가 날아감 → `**decision` spread로 보존

## 구조 개선

### 프롬프트 v7 개편
- 한국어 혼합 → 영어 XML 구조 (`<system>`, `<stock-info>`)
- `<context>`: 현재시각, 보유현금, 수수료, 오늘 매매 성적 요약
- `<rules>`: 진입 규칙, sources 정의, 응답 언어 등
- `<response-format>`: JSON 스키마
- `<stock-info>`: 종목별 데이터 + today_trades 내장

### today_trades 통합
- 기존: `<최근거래이력>` (5분) + `<오늘매매이력>` (청산건) 별도 블록
- 변경: BUY 기준으로 종목별 `<stock-info>` 안에 `today_trades` 내장
  - sell이 있으면 청산 완료 (기존 오늘매매이력)
  - sell이 null이면 미청산 (기존 최근거래이력)
  - 두 블록을 완전히 대체

### sources type 재정의
- 기존: `market|news|dart|ws` (애매)
- 변경: `candles|orderbook|fundamental|news|disclosures|today_trades` (stock_info 키와 1:1 매칭)

### KIS WebSocket 직접 구현
- pykis WebSocket 의존 제거
- 체결(H0STCNT0) + 호가(H0STASP0) 직접 파싱
- approval_key 파일 캐싱으로 재발급 최소화
- pykis 호가 파싱 에러 근본 해결

## 신규 기능

### 데이터 수집
- **호가 잔량** (orderbook): ask_volume/bid_volume/total 수집 및 프롬프트 포함
- **체결 매수/매도 수량**: buy_qty/sell_qty 틱에 저장 (분봉 체결강도 계산 준비)

### 매매 추적
- **buy_order_id**: SELL 주문에 매칭 BUY 주문 ID 기록 → 정확한 페어링
- **판단이력 종목명**: analysis 배열에서 stock_name fallback
- **판단이력 sources 컬럼**: 테이블에 소스 배지 표시

### 프론트엔드
- **탭 유지**: URL 쿼리 파라미터로 새로고침 시 탭 상태 유지 (TradesPage, NewsPage, SettingsPage)
- **주문이력 상세**: row 클릭 시 탭 이동 대신 같은 탭에서 DecisionDetail 펼침

### 인프라
- **배포 텔레그램 알림**: 성공/실패 시 알림 (실패 단계 표시)

## 자산 초기화 (2026-03-25 장 마감 후)
- 기존: 현금 6,106원 + 카카오 13주(638,950원)
- 초기화: **현금 1,000,000원**, 보유 종목 없음
- 사유: 3/24~25 기간에 치명적 버그(현재가 오류, 거래량 오류, 호가 미수집 등) 수정 + 프롬프트 v7 전면 개편이 완료되어, 깨끗한 상태에서 3/26부터 실전 성과 측정 시작

## 남은 과제
- 분봉별 체결강도 계산 (buy_qty/sell_qty 차분 → minute_candles 컬럼)
- 호가를 보조지표로 제한하는 규칙 검토 (데이터 축적 후 판단)
- 하락장 인식 강화 (전체 시장 추세 컨텍스트)
- sell 프롬프트 XML 구조 개선 검토
- pykis WebSocket 기존 코드 정리 (새 코드 안정화 확인 후)
