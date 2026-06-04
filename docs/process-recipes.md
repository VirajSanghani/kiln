# KILN — Process Recipes & the Stage Engine (Phase 2)

Implements Part II of the build plan. **One engine, driven by recipe DATA.** The engine
(`api/app/stage_engine.py`) contains no per-process branches — every decision reads the
recipe registry (`api/app/recipes/`). Adding a process is a data change, never an engine
change.

- Engine: `api/app/stage_engine.py` · Recipes: `api/app/recipes/registry.py`
- Reuses the Phase-1 folds (`api/app/audit.py`) so the reconcile guard stays green.
- Tests: `api/tests/test_recipe_engine.py` (the Phase 2 gate).

---

## 1. The recipe (recap)

A recipe is an ordered list of `StageDef{name, label, type(active|passive),
allowed_next[]}`. The list order is the timeline spine; `allowed_next` is the legal-edge
graph. Entry = first element (`printing`); terminal = empty `allowed_next` (`done`).

| Process | Recipe (A = active, P = passive) |
|---|---|
| FDM | printing(A) → support_removal(A) → qc(A) → **done(P)** |
| SLA | printing(A) → drain(P) → wash(A) → cure(A) → qc(A) → **done(P)** |
| SLS | printing(A) → cooldown(P) → depowder(A) → qc(A) → **done(P)** |
| MJF | printing(A) → cooldown(P) → depowder(A) → {dye(A) │ qc} → qc(A) → **done(P)** |

MJF's `depowder.allowed_next = (dye, qc)` is a real branch: Dye is optional, so depowder
may advance to `dye` or skip straight to `qc`. Both edges are legal; anything else is not.

---

## 2. The engine API

All ops take `(session, build_or_job, ...)`, **flush but do not commit** — the caller owns
the transaction, so a single `commit()` persists the event and the recomputed column
atomically.

### Build-level
| Op | Effect | Preconditions |
|---|---|---|
| `start(build)` | enter at `printing`, record the entry event, set `started_at` | not already started |
| `advance(build, to_stage)` | one legal step along `allowed_next`; on terminal → `completed` + `completed_at` + `on_done` hook | running (not held/terminal) and `to_stage ∈ allowed_next` |
| `hold(build)` | `status → on_hold`, **parks** `current_stage` | running |
| `resume(build)` | `status → running`, **restores** parked stage | on hold |
| `fail(build, reason)` | `status → failed`, parks stage | not already terminal (running **or** on hold) |
| `cancel(build)` | `status → cancelled`, parks stage | not already terminal |

### Per-Job overrides (G1 clause 1)
| Op | Effect |
|---|---|
| `reject_job(job)` | `terminal_status = qc_rejected`, `qc_outcome = failed` |
| `fail_job(job, reason)` | `terminal_status = failed`, records `fail_reason` |
| `cancel_job(job)` | `terminal_status = cancelled` |

A Job override writes a job-scoped StageEvent (carrying the Build context) and touches
**only that Job** — its plate-mates are unaffected. Double-overriding a terminal Job is
rejected.

### Pure validation
`assert_advance_allowed(process, current_stage, to_stage)` — no DB, registry only. Raises
`TransitionError` (with the allowed set) on an illegal edge. This is the surface the
recipe-as-data test drives against a synthetic process.

---

## 3. Invariants & how they're upheld

**Invalid transitions are hard errors, never silent no-ops.** `advance` rejects (a) a
non-edge (`printing → qc`), (b) advancing a held Build (resume first), and (c) advancing a
terminal Build — each with a message naming the build, the attempted edge, and the allowed
set. The Build's state is untouched by a rejected attempt.

**Two-axis side-states (the lossless hold).** `current_stage` is the recipe position;
`status` is the overlay. `hold` writes a `→ on_hold` event and recomputes — the fold sets
`status = on_hold` while **leaving `current_stage` parked** at its recipe position. `resume`
writes an event whose `to_stage` is that parked stage, so the fold restores
`status = running` at exactly where it left off. `fail`/`cancel` work the same way (and
`fail` is reachable from a hold).

**One transaction, reusing the folds.** Every op appends the StageEvent then calls the
Phase-1 `recompute_*` (which folds the append-only log into the mutable column) before
returning. Event and column move together; `reconcile_all` (`column == fold(events)`)
passes after every sequence — asserted by `_commit_ok()` in the gate tests and verified
live against Postgres.

**Multi-Job advancement is free.** Job status is *derived* from the Build (G1 clause 2), so
advancing the Build advances every non-overridden Job with **zero per-Job writes**. A Job
with a terminal override (G1 clause 1) keeps its overridden status and never blocks the
others. Example (seeded + tested): a 3-Job FDM plate where one part is `reject_job`'d
mid-build still reaches `done` for the other two; the rejected part stays `qc_rejected`.

**Recipe-as-data, proven.** `test_adding_a_process_needs_no_engine_edits` registers a
brand-new `DLP_TEST` recipe at runtime and the engine validates its edges correctly with
**no engine code changed**. The engine references zero process names. Adding a real
process = a recipe entry + a `ProcessType` enum value + a one-line enum migration — all
data/schema, never engine logic.

---

## 4. Scope fence

Material decrement + per-Job allocation + ready-for-pickup notifications on Done are **not**
in the engine — that is Phase 4 (inventory/API). The `on_done(build)` hook marks the seam
and is currently a documented no-op, keeping Phase 2 fenced to stage logic.

---

## 5. Gate (all green)

`docker compose run --rm --no-deps --entrypoint pytest api -q` — 29 passed.

- ✅ FDM / SLA / SLS / MJF each walk `printing → done` (data-driven walk); MJF dye-skip too.
- ✅ invalid transition rejected with the allowed set; can't advance a completed or held Build.
- ✅ fail from running **and** from hold; cancel mid-stage; hold/resume lossless midway.
- ✅ 3-Job Build with one `qc_rejected` override → the other two reach `done`.
- ✅ `reconcile_all == []` after every sequence (SQLite gate + live Postgres run).
- ✅ recipe-as-data: a synthetic process drives the engine with no engine edits.
