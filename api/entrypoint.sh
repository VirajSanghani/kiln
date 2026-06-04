#!/usr/bin/env sh
set -e

echo "[entrypoint] applying database migrations (alembic upgrade head)..."
alembic -c /app/db/alembic.ini upgrade head

echo "[entrypoint] starting API (uvicorn)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
