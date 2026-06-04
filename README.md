# KILN

> Working title (final name deferred to Phase 6). A real, deployable print-lab
> operations system for multi-process additive manufacturing (FDM · SLA · SLS · MJF):
> tickets, a capability-aware scheduler, a Build/Job model, process-specific stages,
> and material inventory — without faking machine telemetry.

This is the engineering build. See `KILN_BUILD_PLAN.md` for the master plan and
`SCHEDULER_DESIGN.md` for the centerpiece scheduler policy. The full engineer's-eye
README + honesty section is a Phase 6 deliverable.

## Status: Phase 0 — skeleton + wireframes

What runs today:
- FastAPI service with honest liveness + readiness health endpoints.
- PostgreSQL via docker-compose, with Alembic wired (empty baseline migration).
- React + Vite + TypeScript shell that calls the API and shows Web→API→DB status live.

No data model yet — that is Phase 1. See `docs/wireframes.md` for the three core
operator screens (drawn before modeling) and `docs/stack.md` for how to run it.

## Quick start

```bash
cp .env.example .env
docker compose up --build
# web  → http://localhost:5173
# api  → http://localhost:8000   (docs at /docs)
```

Full run instructions, versions, and the SQLite local-dev fallback are in
[`docs/stack.md`](docs/stack.md).
