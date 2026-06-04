# KILN API — dev image (Phase 0)
# Pinned to 3.12 for broad wheel availability (host may run newer Python).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/api

WORKDIR /app

# Dependencies first for layer caching.
COPY api/requirements.txt api/requirements-dev.txt /app/api/
RUN pip install --no-cache-dir -r /app/api/requirements.txt -r /app/api/requirements-dev.txt

# App code + migrations (migrations live in db/ per the repo structure).
COPY api/ /app/api/
COPY db/ /app/db/

RUN chmod +x /app/api/entrypoint.sh

WORKDIR /app/api
ENTRYPOINT ["/app/api/entrypoint.sh"]
