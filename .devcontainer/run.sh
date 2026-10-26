#!/usr/bin/env bash
# Starts the wallboard (API + built React app) on port 8000. Log: /tmp/wallboard.log
set -e
cd "$(dirname "$0")/.."

# PostgreSQL runs inside this codespace. A codespace made by an older setup (or whose
# first-time setup did not finish) has none yet: install everything first.
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  echo "PostgreSQL is not installed in this codespace yet; running the one-time setup (a few minutes)..."
  bash .devcontainer/setup.sh
fi
pg_isready -q -h 127.0.0.1 2>/dev/null || sudo service postgresql start
export DATABASE_URL=postgresql+asyncpg://wallboard:wallboard@127.0.0.1:5432/wallboard

python -c "import uvicorn, fastapi, asyncpg" 2>/dev/null || pip install --user -r backend/requirements.txt
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

pkill -f "uvicorn app.main:create_app|app.serve" 2>/dev/null || true
cd backend
export STATIC_DIR=../frontend/dist
exec python -m app.serve 8000
