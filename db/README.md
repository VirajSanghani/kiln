# db/ — migrations & seed

Alembic migrations live here (per the repo structure in `KILN_BUILD_PLAN.md` Part VIII),
kept separate from the API service code.

## Running migrations
The API container runs `alembic -c /app/db/alembic.ini upgrade head` on startup
(see `api/entrypoint.sh`). To run by hand:

```bash
# inside the api container
docker compose exec api alembic -c /app/db/alembic.ini upgrade head

# or locally against the SQLite fallback (from repo root)
cd db && DATABASE_URL="sqlite:///../kiln_dev.db" alembic upgrade head
```

## State
- `0001_baseline.py` — empty baseline establishing the version chain (Phase 0).
- Phase 1 adds the real schema migration and wires `target_metadata` in `env.py`.
- The seed script (printers across all 4 processes, material shelf, sample
  tickets/builds/jobs, a couple of failures) lands in Phase 1.
