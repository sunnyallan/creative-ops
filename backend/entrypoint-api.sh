#!/usr/bin/env bash
# API service entrypoint: run migrations, then start Uvicorn.
# ONLY the API service runs migrations — worker + beat use the plain
# start commands set in Railway. This avoids the race where 3 replicas
# would fight over alembic_version at boot.
set -euo pipefail

echo "[entrypoint] applying database migrations…"
alembic upgrade head
echo "[entrypoint] migrations complete, starting API"

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
