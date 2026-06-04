# KILN — Data Model (Phase 1)

Implements Part III of `KILN_BUILD_PLAN.md`. The **Build/Job split** and the
**FileVersion chain** exist from this first migration (`0002_core_schema`), not as a
retrofit. Status is **derived**, never stored as a single field; the append-only logs are
the truth-of-record and the mutable columns are guarded by a reconcile check.

- Models: `api/app/models.py` · Enums: `api/app/enums.py`
- Recipes (data): `api/app/recipes/registry.py`
- Derivation (G1, R4): `api/app/derivation.py` · Audit/reconcile: `api/app/audit.py`
- Migration: `db/migrations/versions/0002_core_schema.py` · Seed: `db/seed.py`

---

## 1. Entities

| Entity | Purpose | Key fields |
|---|---|---|
| **User** | requester or operator (role drives the UI) | `username`*, `display_name`, `role{operator,requester}`, `password_hash?` (auth is a later phase) |
| **Material** | a thing consumed by Builds | `kind{filament,resin,powder,agent}`, `spec`, `color?`, `unit`, **`qty_remaining`** (fast-read), **`reorder_threshold?`** (R6), `lot?`, `opened_date?`, `shelf_life_days?`, `drying_state?`, `virgin_qty?`/`used_qty?` (powder) |
| **Printer** | one machine | `name`*, `process`, `status{idle,printing,down,maintenance}`, `build_volume_{x,y,z}`, `loaded_material?`, **`capabilities` (JSON)** — scheduler input |
| **Ticket** | the human request | `requester`, `title`, `target_process`, `material_pref?`, `priority{critical,high,normal,low}`, `deadline?`, `current_file_version?`. **Status is derived (R4).** |
| **FileVersion** | an uploaded STL/gcode + slicer estimates; **chains per ticket** | `ticket`, `version_no` (unique per ticket), `filename`, `blob_key`, `checksum?`, `size_bytes?`, `slicer_name?`, `est_time_seconds?`, `est_material_qty?/unit?` (always shown "slicer est."), `bbox_{x,y,z}?` (fit) |
| **Build** | **one physical run on one Printer**; carries ≥1 Job | `printer`, `process`, `material?`, **`current_stage`** (recipe position), **`status{running,on_hold,failed,cancelled,completed}`** (side-state overlay), `started_at?`, `completed_at?` |
| **Job** | one ticket's part on one Build | `ticket`, **`file_version?`** (R3: the version that *printed*), `build?` (null pre-Build), **`queue_state{submitted,queued,scheduled}`**, **`terminal_status?{failed,qc_rejected,cancelled}`**, `qc_outcome?`, `fail_reason?`, `allocated_qty?/unit?`, `created_at`, **`queued_at?`** (R5) |
| **StageEvent** | append-only stage/lifecycle transition | `build?`, `job?`, `from_stage?`, `to_stage`, `actor?`, `at`, `note?` |
| **InventoryTxn** | append-only material movement | `material`, `build?`, `delta` (±), `reason{restock,consume,adjust}`, `actor?`, `at`, `note?` |
| **Notification** | per-user in-app inbox item | `user`, `ticket?`, `job?`, `kind{started,failed,ready_for_pickup,on_hold}`, `message`, `read` |

\* unique. `?` = nullable.

### Why a Job pins its own FileVersion (R3)
`Ticket.current_file_version` is "the latest version on the request." `Job.file_version`
is "the version that actually went on this Build." They differ during a re-print: v2
Failed on an old Build (a Job pinned to v2), v3 is current and Printing (a Job pinned to
v3). Recording it on the Job is what makes "which version printed?" answerable forever.

### The Build/Job split, concretely
A Build is one plate/chamber run. It holds one or more Jobs, each tied to a different
ticket/requester (a batched plate). **Stages track at the Build** — the whole plate
washes/cures/depowders together. **Material decrements once per Build** (a single
`InventoryTxn` on Done) and is *allocated* to Jobs (`Job.allocated_qty`) for accounting.
This is what makes SLS/MJF (many nested parts in one powder volume) and shared resin
plates real rather than a one-job-per-print fiction.

---

## 2. The recipe (data, not code) — R1, R2

A recipe is an **ordered list** of stage defs, each `{name, label, type(active|passive),
allowed_next[]}` (`api/app/recipes/registry.py`). Adding a process = adding a list entry.

- **R1 — the recipe spans `printing → done`.** The pre-Build spine
  (`submitted → queued → scheduled`) lives *outside* the recipe, on the Job
  (`queue_state`), because those states exist before any Build does.
- **R2 — the terminal stage is the one whose `allowed_next` is empty** (`done`). The entry
  stage is the first list element (`printing`).
- The **list order** is the timeline/display spine; **`allowed_next`** is the legal-edge
  graph the Phase 2 engine will validate against. They are intentionally distinct: MJF's
  `depowder.allowed_next = (dye, qc)` is a real branch (optional Dye).
- **Side-states** (`on_hold`, `failed`, `cancelled`) are universal — reachable from any
  stage — and deliberately **not** in any `allowed_next`.
- **`type` (active|passive)** drives the timeline colouring and the Phase 6 utilization
  metric (active = machine/operator busy, e.g. Printing/Wash/Depowder; passive = elapsing,
  e.g. Cooldown/Drain).

| Process | Recipe (type) |
|---|---|
| FDM | printing(A) → support_removal(A) → qc(A) → **done(P)** |
| SLA | printing(A) → drain(P) → wash(A) → cure(A) → qc(A) → **done(P)** |
| SLS | printing(A) → cooldown(P) → depowder(A) → qc(A) → **done(P)** |
| MJF | printing(A) → cooldown(P) → depowder(A) → {dye(A)?} → qc(A) → **done(P)** |

> The recipe *engine* (validating transitions, applying side-states, writing the event +
> column in one transaction) is **Phase 2**. Phase 1 ships the recipe *data* plus the
> derivation/audit that consume it.

---

## 3. Status derivation

Status is computed, never stored in one field, so the rules live in exactly one place
(`api/app/derivation.py`).

### 3.1 Job effective status — **G1, verbatim**
> **terminal override** (Failed / QC-rejected / Cancelled)
> → else **inherited Build stage** (if the Job is on a Build)
> → else its own **pre-Build queue state**.

```
job_effective_status(job):
    if job.terminal_status is not None:            return job.terminal_status   # 1
    if job.build_id is not None:                   return build_state(job.build) # 2
    return job.queue_state                                                       # 3
```
Clause 3 is the clause the original G1 wording assumed away — pre-Build Jobs
(Queued/Scheduled, all over the queue board) have no Build to inherit from. A Build's
externally-visible state is the **side-state overlay if set** (`failed`/`cancelled`/
`on_hold`), else its **recipe position** (`current_stage`, which is `done` when completed).

**Headline case (seeded):** a shared Build is `Done`, but one part failed QC — that Job
carries `terminal_status = qc_rejected`, and clause 1 makes it read `qc_rejected` while its
plate-mates read `done`.

### 3.2 Ticket status — **R4**
Ticket → Job is **one-to-many** (multi-part future-safe; v1 seeds one Job per ticket, but
the rule is the multi-part rule from the start). Ticket status =

1. the **least-advanced non-terminal** job's status (so an in-flight re-print outranks a
   finished-but-failed earlier attempt), where "advancement" is the coarse lifecycle rank
   `submitted < queued < scheduled < printing < (mid-build / on_hold) < done`;
2. **tie-break: latest `created_at`** within the same advancement level;
3. if **every** job is terminal (`failed`/`qc_rejected`/`cancelled`/`done`), the
   **latest-by-`created_at`** job's status — so a re-print whose newest attempt is Done
   reads `done`, and one whose newest attempt Failed reads `failed`.

The rank is deliberately coarse: ticket rollup only needs ordering across the spine, and a
per-stage rank would buy nothing.

---

## 4. Pragmatic audit + reconcile (NOT event-sourcing)

`StageEvent` and `InventoryTxn` are **append-only truth-of-record** — nothing in the
codebase updates or deletes them (a policy, plus the `stage_events` CHECK that every event
targets a build and/or job). The mutable convenience columns are **fast reads written in
the SAME transaction** as their event, so they cannot drift:

| Mutable column | Folded from |
|---|---|
| `Build.current_stage`, `Build.status` | build-level StageEvents (`build_id` set, `job_id` null) |
| `Job.queue_state` | pre-Build StageEvents (`job_id` set, `build_id` null, queue vocabulary) |
| `Job.terminal_status` | job override StageEvents (`to_stage ∈ {failed,qc_rejected,cancelled}`) |
| `Material.qty_remaining` | `sum(InventoryTxn.delta)` |

**StageEvent carries three flavours**, disambiguated by which FKs are set + the `to_stage`
vocabulary: build-level transitions, job pre-Build queue transitions, and job terminal
overrides. The build fold keeps `current_stage` parked at its recipe position across a
side-state (a hold sets `status` only), so the recipe position survives a hold.

### The reconcile check (runnable)
`api/app/audit.py::reconcile_all(session)` asserts **every mutable column == fold(events)**
and returns the discrepancies. As a CLI:

```bash
docker compose exec api python -m app.audit
# -> "RECONCILE OK — every mutable column matches fold(events)."  (exit 0)
#    or lists each drift and exits 1   (CI / pre-deploy guard)
```

This buys full auditability ("what happened to job 241?", "where did the PA12-CF go?")
without the read-path and migration tax of full event-sourcing — which would be
over-engineering for this domain. We say so plainly.

> **Powder virgin/used caveat:** the core reconcile invariant is on `qty_remaining`.
> `virgin_qty`/`used_qty` are display annotations for the refresh-ratio in v1; per-stream
> transactional accounting is a documented Phase 4 inventory refinement.

---

## 5. Migrations & seed

- **Real Alembic migration**, not `create_all`. Chain: `0001_baseline` (empty) →
  `0002_core_schema` (all 10 tables, FKs, indexes, the shared enum types, the CHECK). The
  downgrade drops the PG enum types too, so it is cleanly reversible (no-op on SQLite).
- Generic `sa.Enum` keeps the **SQLite local-dev** migration path working (renders as
  VARCHAR + CHECK); on Postgres it creates native enum types, reused across tables.
- **Seed** (`db/seed.py`, `docker compose exec api python /app/db/seed.py`): 4 users,
  5 printers across all 4 processes, a 7-material shelf (some with reorder thresholds, some
  without), 13 tickets / 15 file versions / 14 jobs / 6 builds / 54 stage events /
  9 inventory txns / 2 notifications. It writes every column via the audit folds (same
  transaction) and self-checks reconcile.

### What the seed deliberately exercises
- **G1 clause 1** — a shared, *Done* FDM Build (Bambu-X1C, PA12-CF) carrying three Jobs
  from three requesters; one is `qc_rejected` (warped at QC) and reads its override while
  the others read `done`.
- **R4 re-print** — "motor bracket": v2 Failed on an old Build, v3 Printing now → ticket
  reads `printing`.
- **G1 clause 3** — Jobs in `submitted` / `queued` (a 3-day-old boost candidate) /
  `scheduled` with no Build, plus a `cancelled` Job.
- **Active vs passive stages** — an FDM Build at `printing` (active) and an SLS Build at
  `cooldown` (passive); also SLA at `wash`, MJF at `depowder`.
- **Inventory** — restock / consume (on the Done build, allocated across its 3 jobs) /
  hand-adjust; low-stock-eligible and threshold-free materials.

---

## 6. Documented seams (not built in Phase 1)
- Recipe transition **engine** + side-state rules → Phase 2.
- Scheduler reads `Printer.capabilities`, `Job` priority/deadline/`queued_at` → Phase 3.
- File upload → blob store (S3 seam), slicer parsing populating `FileVersion` estimates,
  inventory write APIs, notification generation → Phase 4.
- `password_hash` exists; auth verification (username/password, roles) → later phase.
