#!/bin/bash

PROJECT_DIR="/Users/jongsoobae/workspace/alt-fast"
SUPERVISORCTL="/Users/jongsoobae/Library/Python/3.9/bin/supervisorctl"
SUPERVISOR_CONF="$PROJECT_DIR/supervisord.conf"

# .env에서 텔레그램 설정 로드
set -a
source "$PROJECT_DIR/backend/.env" 2>/dev/null || true
set +a

send_telegram() {
    local msg="$1"
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TELEGRAM_CHAT_ID" \
            -d text="$msg" > /dev/null 2>&1
    fi
}

set -e
trap 'send_telegram "[DEPLOY FAIL] 배포 실패 — 단계: ${STEP:-unknown}, 로그: /var/log/alt-fast/deploy.err.log"' ERR

cd "$PROJECT_DIR"

STEP="git pull"
echo "=== git pull ==="
git pull origin main

STEP="backend dependencies"
echo "=== backend dependencies ==="
cd "$PROJECT_DIR/backend"
uv sync --quiet

STEP="frontend build"
echo "=== frontend build ==="
cd "$PROJECT_DIR/frontend"
npm ci --silent
npm run build

STEP="nginx reload"
echo "=== nginx reload ==="
nginx -s reload

STEP="supervisor restart"
echo "=== supervisor restart ==="
$SUPERVISORCTL -c "$SUPERVISOR_CONF" restart all

echo "=== deploy complete ==="
send_telegram "[DEPLOY OK] 배포 완료 — $(git -C $PROJECT_DIR log --oneline -1)"
