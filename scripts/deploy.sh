#!/bin/bash
set -e

PROJECT_DIR="/Users/jongsoobae/workspace/alt-fast"
SUPERVISORCTL="/Users/jongsoobae/Library/Python/3.9/bin/supervisorctl"
SUPERVISOR_CONF="$PROJECT_DIR/supervisord.conf"

cd "$PROJECT_DIR"

echo "=== git pull ==="
git pull origin main

echo "=== backend dependencies ==="
cd "$PROJECT_DIR/backend"
uv sync --quiet

echo "=== frontend build ==="
cd "$PROJECT_DIR/frontend"
npm ci --silent
npm run build

echo "=== nginx reload ==="
nginx -s reload

echo "=== supervisor restart ==="
$SUPERVISORCTL -c "$SUPERVISOR_CONF" restart all

echo "=== deploy complete ==="
