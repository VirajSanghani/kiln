# KILN — Deploy (PREPARED, not executed)

These steps are ready to run but **have not been executed** — no host, no push. They are
here for review and a one-command production bring-up.

## Production stack (local prod parity)

`docker-compose.prod.yml` differs from dev: web is a **multi-stage nginx static image**
(no Vite, no bind mounts), the api runs **uvicorn with 4 workers**, blobs use a named
volume, and nothing is source-mounted. nginx serves the SPA and reverse-proxies `/api` to
the api service (same origin → no CORS).

```bash
cp .env.example .env
# EDIT .env: set a strong JWT_SECRET and POSTGRES_PASSWORD before exposing anything
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml exec api python /app/db/seed.py   # optional demo data
# app → http://localhost:8080
```

Migrations run automatically on api start (`alembic upgrade head`). The web production
image has been verified to build (`docker build -f web/Dockerfile.prod ./web`).

## Pre-flight checklist
- [ ] `.env`: real `JWT_SECRET` (rotate from the dev default), real `POSTGRES_PASSWORD`.
- [ ] `DATABASE_URL` points at the managed Postgres (or the compose `db`).
- [ ] Blob storage: dev uses a named volume; for real prod, point `STORAGE_DIR` at a mounted
      disk or swap `app/storage.py` for the S3-compatible backend (the function boundary is
      the seam — `save_blob`/`read_blob`).
- [ ] TLS terminates at the host/load-balancer in front of nginx.
- [ ] Back up the `pgdata_prod` volume (or use a managed Postgres with backups).

## Hosted options (prepared, pick one — DO NOT deploy without sign-off)

**Fly.io** — two apps (api, web) + Fly Postgres, or a single machine running compose.
```bash
fly launch --no-deploy           # in repo root; review generated fly.toml
fly postgres create              # managed PG; set DATABASE_URL secret
fly secrets set JWT_SECRET=...   # never commit it
fly deploy                       # ← requires explicit go
```

**Railway** — new project → add PostgreSQL plugin → deploy api (Dockerfile) and web
(Dockerfile.prod) services → set `DATABASE_URL`/`JWT_SECRET` env → expose web. (`railway up`.)

**VPS (single host)** — `docker compose -f docker-compose.prod.yml up -d` behind Caddy or
nginx for TLS; point a domain at the host; back up the Postgres volume.

## Rollback
Images are tagged per build; `docker compose ... up -d` the prior tag. Schema rollback:
`alembic -c /app/db/alembic.ini downgrade -1` (migrations are reversible — `0002` drops its
enum types cleanly).

## What is intentionally NOT automated
No CI/CD pipeline, no secret manager wiring, no autoscaling — out of scope for v1 and
documented as seams. Deployment is a human action behind an explicit go.
