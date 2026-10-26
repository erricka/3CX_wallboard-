#!/usr/bin/env bash
# Starts the wallboard (API + built React app) on port 8000. Log: /tmp/wallboard.log
cd "$(dirname "$0")/../backend"
export STATIC_DIR=../frontend/dist
exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
