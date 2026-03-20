# ALT-Fast

한국 주식 자동매매 LLM 시스템

## 서버 구성

```
외부 → Cloudflare → cloudflared → nginx(:8080) → 정적파일(frontend/dist) / uvicorn(:8000)
프로세스 관리: supervisor → web, news, market, dart, trader, ws
배포: git push → GitHub Webhook → /api/deploy → scripts/deploy.sh
```

## 주요 경로

| 구분 | 경로 |
|------|------|
| 프로젝트 | `/Users/jongsoobae/workspace/alt-fast` |
| 백엔드 venv | `backend/.venv` |
| 프론트 빌드 | `frontend/dist` |
| supervisor 설정 | `supervisord.conf` |
| nginx 설정 | `/opt/homebrew/etc/nginx/servers/alt.jscraft.work.conf` |
| cloudflared 설정 | `/etc/cloudflared/config.yml` |
| 로그 | `/var/log/alt-fast/` |
| 환경변수 | `.env` |

## 프로세스 관리 (supervisor)

```bash
# supervisorctl 경로
SCTL="/Users/jongsoobae/Library/Python/3.9/bin/supervisorctl"
CONF="/Users/jongsoobae/workspace/alt-fast/supervisord.conf"

# 상태 확인
$SCTL -c $CONF status

# 전체 재시작
$SCTL -c $CONF restart all

# 개별 재시작
$SCTL -c $CONF restart web
$SCTL -c $CONF restart collectors:news
$SCTL -c $CONF restart collectors:market
$SCTL -c $CONF restart collectors:dart
$SCTL -c $CONF restart collectors:trader
$SCTL -c $CONF restart collectors:ws

# supervisord 자체 시작 (서버 재부팅 후)
/Users/jongsoobae/Library/Python/3.9/bin/supervisord -c $CONF
```

## 로그 확인

```bash
# 웹서버
tail -f /var/log/alt-fast/web.log
tail -f /var/log/alt-fast/web.err.log

# 수집기
tail -f /var/log/alt-fast/news.log
tail -f /var/log/alt-fast/market.log
tail -f /var/log/alt-fast/dart.log
tail -f /var/log/alt-fast/trader.log
tail -f /var/log/alt-fast/ws.log

# 배포
tail -f /var/log/alt-fast/deploy.log
tail -f /var/log/alt-fast/deploy.err.log
```

## nginx

```bash
# 설정 테스트
nginx -t

# 리로드
nginx -s reload
```

## cloudflared

```bash
# 설정 수정 후 재시작
sudo vi /etc/cloudflared/config.yml
sudo pkill cloudflared
```

## 배포

push하면 GitHub Webhook이 자동 배포합니다.

수동 배포:
```bash
cd /Users/jongsoobae/workspace/alt-fast
./scripts/deploy.sh
```

## 개발 (로컬)

```bash
# 백엔드
cd backend
.venv/bin/uvicorn app.main:app --reload

# 프론트엔드
cd frontend
npm run dev

# 셸 (Django shell 대용)
cd backend
.venv/bin/ipython -i shell.py
```

## DB

```bash
# PostgreSQL (Docker)
docker exec -it my-postgres psql -U postgres -d alt_fast

# 마이그레이션
cd backend
.venv/bin/alt db migrate
```

## 외부 서비스

| 서비스 | 용도 | 설정키 |
|--------|------|--------|
| KIS API | 주식 시세/주문 | `KIS_APP_KEY`, `KIS_APP_SECRET` |
| 네이버 뉴스 API | 뉴스 수집 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| DART API | 공시 수집 | `DART_API_KEY` |
| Gemini API | 챗봇 LLM | `GEMINI_API_KEY` |
| Cloudflare Tunnel | 외부 접속 | `/etc/cloudflared/config.yml` |
| GitHub Webhook | 자동 배포 | `WEBHOOK_SECRET` |
