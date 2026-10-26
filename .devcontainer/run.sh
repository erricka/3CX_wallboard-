#!/usr/bin/env bash
# Starts the wallboard (API + built React app) on port 8000. Log: /tmp/wallboard.log
set -e
cd "$(dirname "$0")/.."

python -c "import uvicorn, fastapi, asyncpg" 2>/dev/null || pip install --user -r backend/requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

pkill -f "uvicorn app.main:create_app" 2>/dev/null || true
cd backend
export STATIC_DIR=../frontend/dist
exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
