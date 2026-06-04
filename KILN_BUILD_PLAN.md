# KILN — Master Build Plan (v2)
### A print-lab operations system for multi-process additive manufacturing
*Tickets · capability-aware scheduler · Build/Job model · process stages · material inventory*

> **KILN** — the place where things are fired and made. (Placeholder — swap freely.)
> **v2** incorporates a full red-team: a dedicated scheduler phase, a Build/Job split,
> slicer-parsed estimates, real file/versioning, in-app notifications, an ops dashboard, and a
> pragmatic audit model (not full event-sourcing). See `SCHEDULER_DESIGN.md` for the centerpiece.

---

## PART I — INTENT

### 1.1 One-sentence pitch
A real, deployable web app that runs a multi-process 3D-printing lab: engineers submit print
tickets (with slicer-estimated time/material), a **capability-aware scheduler** orders the work,
jobs run individually or batched onto shared **Builds**, every Build moves through
**process-specific stages** (FDM ≠ SLA ≠ SLS ≠ MJF), and a **material inventory** tracks
consumption and warns on low stock — without blocking the operator or faking machine telemetry.

### 1.2 What this proves (complements VARA)
VARA proved hardware/CAD/product depth. KILN proves **operational + systems depth**: data
modeling, lifecycle/state design, multi-process domain knowledge, scheduling judgment, and the
sense to build software a technician would actually live in. Together: the hands AND the systems
brain — the two halves of the role.

### 1.3 The north star
**Genuinely useful to a real lab.** Every feature faces one test: *would the technician who lives
in this all day keep it, or rip it out?* This killed full event-sourcing (gold-plating) and the
gamification ideas; it kept the failure-reasons and the ops dashboard.

### 1.4 Honesty rules (carried from VARA)
1. **No faked telemetry.** Statuses are human-updated (someone observed it). Only a `ManualAdapter`
   is implemented; `Moonraker`/`OctoPrint` adapters are a STUBBED, documented future seam.
2. **Inventory informs, never blocks.** Flags projected shortfalls, decrements on Done — never
   prevents queuing. Real labs override.
3. **Estimates are labeled estimates.** Print time + material come from parsed SLICER output and
   read "slicer est." — slicers themselves are ~10–20% off; never implied as measured.
4. **Pragmatic audit, honestly framed.** Append-only logs are the truth-of-record; mutable status
   columns are fast-read convenience, written in the same transaction so they can't drift. We do
   NOT claim full event-sourcing — that would be over-engineering, and we say so.

---

## PART II — THE CORE INSIGHT

> **Tickets and the queue are universal. Stages and material accounting are process-specific.
> A Build is one physical run; it may carry many Jobs.**

Two ideas drive the architecture:
1. One engine; a per-process **recipe** (data, not code branches) defines stages + consumption.
   Adding a process = adding a recipe, never editing the engine.
2. The **Build/Job split**: a *Build* is one physical plate/chamber run on one printer; it
   contains one or more *Jobs* (each tied to a ticket/requester). Stages track at the **Build**
   level (the whole plate washes/cures/depowders together); ticket/job status is **derived** from
   its Build; material decrements **once per Build** and allocates to Jobs for accounting. This is
   what makes SLS/MJF (many nested parts in one powder volume) and shared resin plates real.

### 2.1 Process recipes
| Process | Stages (after Printing) | Material | Notable accounting |
|---|---|---|---|
| **FDM** | Support removal → QC → Done | Filament spool, g | decrement g; drying state (PA/PETG); color/material match |
| **SLA** | Drain → Wash → Cure → QC → Done | Resin, mL | decrement mL; resin shelf life + exposure profile |
| **SLS** | Cooldown → Depowder → QC → Done | Powder, g | **refresh ratio** (used+fresh blend); virgin/used mix |
| **MJF** | Cooldown → Depowder → (Dye) → QC → Done | Powder + agent | powder refresh + per-part agent |

### 2.2 Lifecycle (universal spine)
`Submitted → Queued → Scheduled(on a Build) → Printing → [process stages] → Done`
Side-states any stage may enter: **Failed** (→ requeue w/ structured reason, notify requester),
**On-hold** (material short / machine down / awaiting info), **Cancelled**. The failure path is
first-class — prints fail; a queue that can't requeue gracefully is lying.

---

## PART III — DATA MODEL (the genuine article)

### 3.1 Entities
- **User** — requester or operator (role drives which UI they get; see Part VI).
- **Printer** — name, process, build volume, status (idle/printing/down/maint), loaded-material
  ref, **capabilities/constraints** (e.g. "PA12-CF only on enclosed") — these feed the scheduler.
- **Material** — kind (filament/resin/powder/agent), spec, color, unit (g/mL), qty_remaining
  (fast-read), lot/opened-date (shelf life), drying state (filament), virgin/used split (powder).
- **Ticket** — requester, title, target process, material pref, priority, deadline, current
  **FileVersion** ref, derived status. The human-facing request.
- **FileVersion** — uploaded STL/gcode blob + slicer-parsed est_time + est_material + slicer name;
  versions chain per ticket ("which version printed" is recorded). Real blob storage.
- **Job** — one ticket's part on one Build. Carries its share of material allocation + per-part
  QC outcome. Status derived from its Build's stage (+ its own QC/fail).
- **Build** — one physical run on one Printer: process, the Jobs it carries, current stage,
  status, stage history. Material decrements here.
- **StageEvent** — append-only: Build (or Job) moved A→B by user U at T (+note). Audit truth.
- **InventoryTxn** — append-only: material consumed (by Build) / restocked / hand-adjusted.
  qty_remaining is reconcilable against the sum of txns.
- **Notification** — per-user in-app inbox item, generated on requester-relevant events
  (started / failed / ready-for-pickup). No email in v1 (documented seam).

### 3.2 Pragmatic audit (NOT full event-sourcing)
Append-only `StageEvent` + `InventoryTxn` are the record of truth and answer "what happened to
job 241?" / "where did the PA12-CF go?". Mutable `current_status` (Build/Job) and `qty_remaining`
(Material) are convenience reads, written in the SAME transaction as the corresponding event so
they can never drift. A periodic reconcile check asserts column == fold(events). This gets full
auditability without the read-path/migration tax of pure event-sourcing.

### 3.3 Inventory↔queue loop (informs, never blocks)
On schedule: project consumption from the Build's Jobs' slicer estimates; show "PETG 24g → leaves
180g (ok)" or "→ -12g (SHORT, flagged)". On Build Done: write InventoryTxn(s), decrement, allocate
to Jobs. Low-stock + shelf-life + drying + powder-refresh warnings surface on the dashboard.
Never a hard stop.

---

## PART IV — TECH STACK (full real, deployable)

- **Backend:** Python + **FastAPI** (typed, fast, suits the recipe engine + audit model).
- **DB:** **PostgreSQL** + SQLAlchemy + Alembic migrations. SQLite = local-dev fallback only.
- **File storage:** blob store for STL/gcode — local volume in dev, **S3-compatible seam** for
  prod. Size cap; checksum per FileVersion.
- **Frontend:** React + Vite + TypeScript, TanStack Query. **Quiet Utility** aesthetic
  (Fraunces + JetBrains Mono, stone/amber). TWO surfaces — operator console + requester portal.
- **Auth:** simple JWT/session, operator vs requester roles. Real but minimal (no enterprise SSO).
- **Slicer parsing:** a small parser module handling PrusaSlicer / Cura / Bambu Studio summary
  formats (time + filament weight/length) — plus a structured manual-paste fallback.
- **Deploy:** Docker compose (api + db + web + minio-for-blobs in dev). One-command up. A real
  hosted option documented (Fly.io / Railway / VPS) — prepared, never deployed without sign-off.
- **Printer seam:** abstract `PrinterAdapter`; only `ManualAdapter` implemented; Moonraker/
  OctoPrint adapters stubbed + documented.

## PART V — PHASED PLAN

> Each phase: real artifact (incl. tests) + STOP for review. Honesty rules hold throughout.

### Phase 0 — Repo + stack probe + screen sketches  *(1 session)*
Stand up the real skeleton (FastAPI + Postgres via compose + Alembic + React shell calling a
health endpoint; confirm `docker-compose up`). ALSO sketch the 3 core operator screens (queue,
ticket/build detail, material shelf) as rough wireframes BEFORE modeling, so the schema serves
the UI rather than speculation.
**Artifact:** running skeleton, `docs/stack.md`, `docs/wireframes.md`.

### Phase 1 — Data model + migrations  *(2 sessions)*
Implement Part III incl. the **Build/Job split** and **FileVersion chain** from the start (not a
retrofit). Pragmatic audit: append-only logs + same-transaction status columns + a reconcile
check. Alembic migrations (no create-all). Seed: printers across all 4 processes, a material
shelf, sample tickets/builds/jobs, a couple of failures.
**Artifact:** migrated DB, seed, `docs/data-model.md`.

### Phase 2 — Process recipe engine  *(2 sessions)* ★ differentiator
Universal lifecycle + per-process recipes as data. Stage transitions validated against the recipe
at the **Build** level; failure/hold/cancel side-states; each transition writes a StageEvent and
updates the status column in one transaction. Tests proving FDM/SLA/SLS/MJF each walk their stages
AND that a multi-Job Build advances all its Jobs correctly.
**Artifact:** recipe engine + tests, `docs/process-recipes.md`.

### Phase 3 — Scheduler  *(2–3 sessions)* ★★ CENTERPIECE — see SCHEDULER_DESIGN.md
Capability-aware sub-queues, the documented ordering policy, no-preemption rule, operator-toggle
same-material batching, and Build assembly (group compatible queued Jobs onto one Build). This is
the part a lab lead will probe — build it as explicit, defensible policy, not an opaque optimizer.
**Artifact:** scheduler module + tests, the policy realized from `SCHEDULER_DESIGN.md`.

### Phase 4 — Tickets, files, slicer parsing, inventory API  *(2–3 sessions)*
Ticket submit with file upload → FileVersion → slicer-parse → estimates. Re-submit = new version.
Job/Build advance/fail/hold/cancel endpoints. Inventory CRUD, event-sourced txns, consumption on
Done, restock, the full warning set. In-app Notification generation on requester-relevant events.
**Artifact:** REST API + tests, `docs/api.md`, `docs/inventory.md`.

### Phase 5 — Frontend (TWO surfaces)  *(4 sessions — the long pole, timeboxed)*
- **Operator console:** scheduler/queue board (process-aware), Build assembly UI, ticket/build
  detail + stage timeline, fleet view, material shelf w/ warnings, the **ops dashboard**.
- **Requester portal:** submit ticket + upload, "my jobs" status, notification inbox.
Real data from the API, no UI mocks. Quiet Utility throughout. If time tightens: operator's three
core screens + dashboard are the must-ship; requester portal trimmed to submit + track.
**Artifact:** the working app, `docs/ui.md`.

### Phase 6 — Ops dashboard hardening, polish, deploy prep, story  *(1–2 sessions)*
Dashboard metrics derived from logs (throughput, utilization %, success rate, queue wait, burn
rate). Dockerized one-command up; seeded demo; README (engineer's-eye + honesty section); deploy
steps PREPARED not executed; LICENSE (MIT — it's software).
**Artifact:** deployable repo + README + shareable demo.

## PART VI — TWO UIs (resolved from red-team)
Operator and requester need different apps. Operator: the full console (queue, builds, fleet,
inventory, dashboard). Requester: a small portal (submit + upload, my-jobs, inbox). Planned from
Phase 5 start, role-gated, sharing the API + design system — not bolted on.

## PART VII — SCOPE FENCES (deliberately NOT built in v1)
- ✗ Faked telemetry / simulated feeds (manual is more honest).
- ✗ Print-settings/orientation optimization (VARA's territory).
- ✗ Slicer *integration* (we PARSE slicer output; we don't slice in-app).
- ✗ Full event-sourcing (pragmatic audit instead — see 3.2).
- ✗ Email/SMS (in-app inbox only), enterprise SSO, billing/chargeback, calendar/Gantt prediction.
- **Documented future seams:** real printer adapters, email notifications, failure-photo gallery,
  QR job labels, cost accounting, scheduler finish-time prediction.

## PART VIII — REPO STRUCTURE
```
kiln/
  api/        FastAPI: models, recipes/, scheduler/, slicer/, adapters/, routers/, tests/
  web/        React + Vite + TS: operator/ + requester/ + shared design system
  db/         Alembic migrations, seed script
  storage/    blob store (dev volume); S3 seam documented
  docs/       stack, wireframes, data-model, process-recipes, api, inventory, ui
  SCHEDULER_DESIGN.md
  docker-compose.yml
  README.md   engineer's-eye story + honesty section
  LICENSE
```

## PART IX — RISKS (named)
| Risk | Mitigation |
|---|---|
| Scope (full stack + 4 processes + scheduler + 2 UIs) is large | Phase gates; recipe+scheduler as data; frontend timeboxed with a stated must-ship subset |
| Build/Job split adds modeling complexity | In schema from Phase 1, not retrofit; tests for multi-Job Builds |
| Scheduler over-cleverness | Explicit documented POLICY, not an opaque optimizer (SCHEDULER_DESIGN.md) |
| Slicer formats vary | Parser handles top 3 + manual structured paste fallback |
| Plumbing eats time (Docker/Postgres/blobs) | compose from Phase 0; SQLite + local-volume dev fallbacks |
| Honesty drift to faked telemetry | ManualAdapter only; others stubbed + labeled |
| Audit columns drift from logs | same-transaction writes + periodic reconcile assertion |
