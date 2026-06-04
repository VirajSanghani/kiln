# KILN — Stack & Run Guide (Phase 0)

The real, deployable stack. Phase 0 stands up the skeleton end to end; later phases add
the data model, recipe engine, scheduler, API, and the two frontends.

## Components & versions

| Layer | Tech | Version (pinned) | Notes |
|---|---|---|---|
| API | FastAPI | 0.115.6 | typed; suits the recipe engine + audit model |
| | uvicorn[standard] | 0.34.0 | ASGI server |
| | SQLAlchemy | 2.0.36 | ORM (models land Phase 1) |
| | Alembic | 1.14.0 | real migrations, **not** `create_all` |
| | psycopg2-binary | 2.9.10 | Postgres driver (bundles libpq) |
| | pydantic-settings | 2.7.0 | env-driven config |
| DB | PostgreSQL | 16 | the real target |
| Web | React | 18.3 | |
| | Vite | 6 | dev server + build |
| | TypeScript | 5.6 | |
| | TanStack Query | 5 | server-state |
| Runtime images | python | 3.12-slim | pinned for broad wheel availability |
| | node | 22-alpine | LTS-line dev image |
| Orchestration | Docker Compose | v2 | `db + api + web` |

> Host toolchain seen at Phase 0: Docker 28.3.2 / Compose v2.38.2, Python 3.14.4,
> Node 25.5.0. The API **image** pins Python 3.12 so wheel availability never depends
> on the host having a bleeding-edge interpreter.

## Run it (Docker — the real path)

```bash
cp .env.example .env          # .env is gitignored
docker compose up --build     # legacy alias: docker-compose up --build
```

Then:
- **Web shell** → http://localhost:5173 (live Web→API→DB status card)
- **API** → http://localhost:8000 · OpenAPI docs at http://localhost:8000/docs
- **Postgres** → localhost:5432 (`kiln`/`kiln_dev_pw`, db `kiln`)

Startup ordering is enforced by healthchecks: `db` (pg_isready) → `api` (after which
the entrypoint runs `alembic upgrade head`) → `web`. `docker compose ps` should show
all three **healthy**.

Stop / reset:
```bash
docker compose down            # stop, keep the pgdata volume
docker compose down -v         # also drop the database volume (clean slate)
```

### Health endpoints (honest, not faked)
- `GET /api/health` — **liveness**. Always `200` if the app is serving.
- `GET /api/health/ready` — **readiness**. Runs a real `SELECT 1`; returns `db:
  "connected"` (`200`) or `db: "unreachable"` (`503`). The web shell polls this, so the
  status dots reflect actual Postgres connectivity — nothing is mocked.

## Run it (local, no Docker — the SQLite fallback)

SQLite is a **local-dev fallback only**; Postgres is the
real target. Useful for fast unit work without containers.

```bash
# API
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# no DATABASE_URL set -> config.py falls back to sqlite:///./kiln_dev.db
PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# migrations against the SQLite fallback (from repo root)
cd db && DATABASE_URL="sqlite:///../kiln_dev.db" alembic upgrade head

# web
cd web && npm install && npm run dev      # proxies /api -> http://localhost:8000
```

> Note: `psycopg2-binary` ships wheels for stable CPython lines. On a very new host
> interpreter (e.g. 3.14) prefer the Docker path, or use the SQLite fallback which
> needs no Postgres driver.

## Tests

```bash
docker compose run --rm --no-deps --entrypoint pytest api -q
```
Phase 0 ships a hermetic smoke test (liveness + root). Recipe tests gate Phase 2 and
scheduler tests gate Phase 3, per `SCHEDULER_DESIGN.md` §9.

## Migrations (Alembic)

- Migrations live in `db/migrations/` (per repo structure, Part VIII), separate from API code.
- `db/alembic.ini` uses `script_location = %(here)s/migrations` so it is path-independent.
- `db/migrations/env.py` reads `DATABASE_URL` from the environment (compose sets it),
  falling back to the ini's SQLite URL. `target_metadata` is `None` in Phase 0 and gets
  wired to the app's `Base.metadata` in Phase 1 for autogenerate.
- Current head: `0001_baseline` — an **empty** baseline that establishes the version
  chain. The schema migration is the first Phase 1 artifact.

## Configuration & secrets

- `.env.example` is committed; `.env` is gitignored. Compose interpolates `${VAR}` from `.env`.
- `JWT_SECRET` is a placeholder; auth (minimal username/password, roles operator|requester)
  arrives in a later phase.

## Documented future seams (not built in Phase 0)

- **Blob storage (MinIO / S3):** STL/gcode storage with an S3-compatible seam — wired in
  **Phase 4** (file upload + FileVersion). Deliberately not added to compose yet so the
  Phase 0 gate stays lean and exercises only what it proves.
- **Web production image:** the web service runs the Vite dev server; a multi-stage
  build + static-serve image is a Phase 6 deploy-prep seam.
- **Printer adapters:** abstract `PrinterAdapter`; only `ManualAdapter` will be
  implemented. Moonraker/OctoPrint are stubbed + documented (no faked telemetry).
- **Hosted deploy:** Fly.io / Railway / VPS — prepared in Phase 6, never deployed
  without explicit sign-off.

## Phase 0 verification (recorded)

```
docker compose ps        → db, api, web all "healthy"
GET :8000/api/health         → {"status":"ok","service":"kiln-api","version":"0.0.0"}
GET :8000/api/health/ready   → {"db":"connected", ...}  [http 200]
GET :5173/                   → 200, <title>KILN — operations</title>
GET :5173/api/health/ready   → {"db":"connected", ...}  [http 200]  (browser → vite proxy → api → postgres)
alembic_version in Postgres  → 0001
pytest                       → 2 passed
```
