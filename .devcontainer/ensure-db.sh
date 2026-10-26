#!/usr/bin/env bash
# Starts PostgreSQL in this codespace and creates the wallboard's user and database if they are missing.
# "sudo runuser" because a codespace user may only sudo to root without a password, not to postgres.
set -e

pg_isready -q -h 127.0.0.1 2>/dev/null || sudo service postgresql start
sudo runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'wallboard'" | grep -q 1 \
  || sudo runuser -u postgres -- psql -qc "CREATE USER wallboard PASSWORD 'wallboard'"
sudo runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'wallboard'" | grep -q 1 \
  || sudo runuser -u postgres -- createdb -E UTF8 -T template0 -O wallboard wallboard
