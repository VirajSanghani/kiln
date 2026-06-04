# KILN — UI (Phase 5)

Two surfaces over the live API, no UI mocks. **Operator console** (the real app) +
a **minimal requester submit page**. React + Vite + TS + TanStack Query. Quiet Utility
aesthetic: Fraunces (display) + JetBrains Mono (data), stone/amber.

Code: `web/src/` — `api.ts` (fetch+token), `auth.tsx` (JWT context), `App.tsx`
(role-based router + shell), `ui.tsx` (shared components), `pages/`, `styles.css`
(design system).

## Surfaces & routing
Login stores a JWT; the router is role-gated. Operators land on the dashboard and see the
full nav; requesters land on `/submit` and see only that. Requester routes that aren't
theirs redirect; cross-role API calls are refused server-side (the UI never has to be
trusted for authz).

### Operator console
- **Ops dashboard** (`/`) — the hero (see below).
- **Queue & Schedule** (`/queue`) — triage lanes (needs-triage → queued → scheduled; the
  triage step stays: submitted jobs require an explicit "→ Queue" action), capability
  buckets with ordered next-up + the *reason* the top job is first + ⚡boosted + swap flags
  + the no-preemption / occupies-machine notes, and the proposals panel with per-process
  batching toggles and **Confirm & start** / dismiss.
- **Build detail** (`/builds/:id`) — the stage timeline (recipe spine, current/done nodes,
  active·passive·on-machine labels, StageEvent actor+time), transition actions (advance to
  each `allowed_next`, hold/resume/fail/cancel), and per-Job rows with a per-part reject.
- **Material shelf** (`/materials`) — stock, reorder thresholds, the warning set
  (severity-coloured), and a restock control.
- **Fleet** (`/fleet`) — printer cards: status (human-updated), loaded material, running
  build/stage, capabilities.
- **Ticket detail** (`/tickets/:id`) — the FileVersion chain (slicer-est labelled) + jobs.

### Requester (minimal)
- **Submit a print** (`/submit`) — submit + file upload (+ optional slicer-summary paste)
  and a "My jobs" status table scoped to the requester. No portal chrome, no inbox UI
  (notifications still generate server-side).

## The dashboard — every figure traces to a query
`/api/dashboard` (`app/metrics.py`) computes each metric from real data; the tile renders
the backing query beneath it (the `↳ …` line) so a viewer can see exactly what it means.
A metric that can't be computed shows **"needs more data"** — never a placeholder.

| Metric | Backing query (`app/metrics.py`) |
|---|---|
| **Throughput** (builds / 14d + sparkline) | `builds WHERE status=completed`, bucketed by `completed_at` date over the window |
| **Fleet utilization** (% + stacked bar) | each printer joined to its running Build; in-use = `status=printing` **or** a running Build in an `occupies_machine` stage |
| **Success rate** (%) | jobs by **derived** status; `done / (done + failed + qc_rejected)` (cancellations excluded) |
| **Avg queue wait** (h) | per job: `(build's first 'printing' StageEvent.at) − job.queued_at`, averaged over jobs that reached printing |
| **Material burn** (consumed + projection) | `Σ(−delta) WHERE reason=consume` grouped by material; in-flight **projection** = `Σ slicer est.` of running builds, labelled **est.** |

Verified live: confirming + advancing a Build to Done moved throughput 1→2, utilization
60→80%, success 50→60%, and PA12-CF burn 60→85g — all from the single real action, with
reconcile still green. Sparse-but-true, by design.

## Honesty at the visible layer
- Slicer-derived figures carry an **est.** badge; printer status is labelled human-updated
  (no telemetry); the queue board states "the scheduler proposes; you dispose — nothing
  auto-starts a machine".
- The dashboard's per-tile query line is the visible expression of the project's core
  discipline: no number appears that can't be traced to the logs.

## Running it
`docker compose up --build` → console at http://localhost:5173 (proxies `/api` to the API).
Demo: operator `rk`/`rk-pw`, requester `ana`/`ana-pw`.

## Trim taken
None of the locked scope was dropped: all operator screens (queue/triage, build detail,
material shelf, **fleet**, ticket detail) + the hero dashboard, plus the minimal requester
submit page, all ship and run against the live API. The pre-authorized trim (thin
fleet/requester) was available but not needed.

## Future seams (not built)
Notification inbox UI; production web image (multi-stage static build) — Phase 6;
optimistic updates / websockets; pagination on long lists.
