# 이벤트 드리븐 전략 전환 — 태스크 목록

## 개요
초단타 전략(PF 0.21, Kelly% -0.89)을 폐기하고, LLM의 비정형 정보 해석 강점을 활용하는 이벤트 드리븐 전략으로 전환한다. 기존 인프라를 최대 활용하고, 새 트레이더 프로세스(event_trader)를 추가하는 방식으로 구축한다.

## 기술 스택
- Python 3.12+ / FastAPI / SQLAlchemy 2.0 (async)
- PostgreSQL / Redis / yfinance (신규)
- Gemini LLM (openai SDK 호환)
- supervisord / Typer CLI

## 타임라인
```
Phase 1  W1       추가 데이터 수집 (Task 01~04)
Phase 2  W2~3     event_trader 구축 + 페이퍼 투입 (Task 05~11)
Phase 3  W4~      운영 + 튜닝 + Go/No-Go (Task 12)
```

## 태스크 목록
| # | 태스크 | 설명 | Phase | 상태 |
|---|--------|------|-------|------|
| 01 | [매크로 데이터 수집기](01-macro-collector.md) | 미장 지수, 환율, 금리 수집 (yfinance) | P1 | ⬜ |
| 02 | [DART 수집 조정](02-dart-interval-reduction.md) | is_processed 플래그 + Redis 알림 | P1 | ⬜ |
| 03 | [뉴스 클러스터링](03-news-clustering.md) | 동일 종목 뉴스 그룹핑 + 클러스터 감지 | P1 | ⬜ |
| 04 | [히스토리컬 백필](04-historical-data-backfill.md) | DART 1년, 분봉 6개월, 뉴스 6개월, 매크로 1년 | P1 | ⬜ |
| 05 | [이벤트 감지](05-event-detection.md) | 공시/뉴스클러스터/거래량급증 감지 모듈 | P2 | ⬜ |
| 06 | [퀀트 필터](06-quant-filter.md) | 거래량/스프레드/시총 룰 기반 필터링 | P2 | ⬜ |
| 07 | [LLM 판단 모듈](07-event-trader-llm-decision.md) | 이벤트 컨텍스트 + 거시 데이터 → LLM 매매 판단 | P2 | ⬜ |
| 08 | [포지션 사이징 + 매수](08-position-sizing-and-execution.md) | 고정/Kelly 사이징 + 가상 매수 실행 | P2 | ⬜ |
| 09 | [청산 로직](09-liquidation-logic.md) | 목표가/손절가/보유기간 기반 청산 + 안전장치 | P2 | ⬜ |
| 10 | [서킷브레이커](10-circuit-breaker.md) | 3연패 정지, 일일 손실 한도, 매매 상한 | P2 | ⬜ |
| 11 | [event_trader 통합](11-event-trader-integration.md) | 메인 루프 + CLI + supervisord 등록 | P2 | ⬜ |
| 12 | [모니터링 + Go/No-Go](12-monitoring-and-go-no-go.md) | 성과 분석 API + 20/50/100건 게이트 | P3 | ⬜ |

## 의존 관계
```
01 ──┬── 04 (매크로 백필)
     └── 07 (매크로 데이터 → 프롬프트)
02 ──── 05 (DART 이벤트 감지)
03 ──┬── 04 (뉴스 백필)
     └── 05 (뉴스 클러스터 이벤트 감지)
05 ──── 06 ──── 07 ──── 08 ──── 09 ──┬── 10
                                      └── 11 ──── 12
```

## 실행 방법
각 태스크 파일을 순서대로 에이전트에게 전달하세요:
```bash
/ralph tasks/01-macro-collector.md 읽고 구현해
```

## 결정사항 (회의록 기반)
1. 기존 인프라 최대 활용, 새 트레이더 프로세스 추가 방식
2. 백테스트 프레임워크는 후순위, 페이퍼 트레이딩으로 실시간 검증
3. 멀티 포지션은 전략 여러 개로 처리 (나중에)
4. Go/No-Go 게이트(20/50/100건) 엄격 적용
5. 50건 게이트 미통과 → 파라미터 수정 후 재시도 최대 2회, 2회 실패 → 전략 재검토
