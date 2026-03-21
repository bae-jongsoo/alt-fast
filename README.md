# ALT

LLM 기반 한국 주식 자동매매 시스템.

실시간 시장 데이터, 뉴스, 공시를 수집하고 LLM이 매수/매도를 판단하여 자동으로 거래합니다.

## 주요 기능

### 자동매매
- LLM이 시장 데이터 + 뉴스 + 공시를 종합 분석하여 매수/매도/관망 판단
- 프롬프트 템플릿을 DB에서 관리 (웹에서 수정 가능)
- 에러 발생 시 텔레그램 알림

### 데이터 수집
- **시장 스냅샷**: KIS API를 통한 종목별 시세/재무 정보
- **뉴스**: 네이버 뉴스 수집 + LLM 요약 + 유용성 판단
- **공시**: DART API를 통한 공시 수집
- **실시간 체결**: KIS WebSocket → Redis → 분봉 생성

### 웹 대시보드
- 자산 요약, 보유종목 평가, 시스템 상태 모니터링
- 매매이력 조회 (주문/판단 이력, LLM 프롬프트/응답 상세)
- 뉴스/공시 조회 (유용성 필터, 요약 확장)
- 설정 관리 (종목, 프롬프트 템플릿, 시스템 파라미터)

### AI 챗봇
- 시스템 데이터를 조회하여 답변하는 AI 어시스턴트
- Function Calling으로 자산/거래/뉴스/시세 조회
- SSE 스트리밍 응답

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI, SQLAlchemy (async), PostgreSQL, Redis |
| Frontend | React, TypeScript, Tailwind CSS, shadcn/ui |
| LLM | OpenClaw (트레이딩), Gemini (챗봇) |
| 외부 API | KIS (한국투자증권), 네이버 뉴스, DART |
| 인프라 | nginx, supervisor, Cloudflare Tunnel |
| 배포 | GitHub Webhook 자동 배포 |
