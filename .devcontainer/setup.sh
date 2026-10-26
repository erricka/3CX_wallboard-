#!/usr/bin/env bash
# One-time codespace setup: PostgreSQL in this container, Python packages, React build.
# Credentials come from .env in the repo root (or a Codespaces secret THREECX_CLIENT_SECRET).
set -e
cd "$(dirname "$0")/.."

# GitHub's default codespace image lists a Yarn package source whose signing key has expired, so
# "apt-get update" reports an error even though the other sources (where PostgreSQL comes from) updated.
sudo apt-get update -qq || echo "Some package sources could not be updated (ignored); installing PostgreSQL anyway..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql > /dev/null
bash .devcontainer/ensure-db.sh

pip install --user -r backend/requirements.txt
(cd frontend && npm ci --no-audit --no-fund && npm run build)
