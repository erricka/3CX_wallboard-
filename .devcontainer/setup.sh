#!/usr/bin/env bash
# One-time codespace setup: PostgreSQL in this container, Python packages, React build.
# THREECX_CLIENT_SECRET comes from a Codespaces secret or a .env file in the repo root.
set -e
cd "$(dirname "$0")/.."

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql > /dev/null
sudo service postgresql start
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'wallboard'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE USER wallboard PASSWORD 'wallboard'"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'wallboard'" | grep -q 1 \
  || sudo -u postgres createdb -E UTF8 -T template0 -O wallboard wallboard

pip install --user -r backend/requirements.txt
(cd frontend && npm ci --no-audit --no-fund && npm run build)
