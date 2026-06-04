# KILN — Scheduler: implementation notes & interpretations (Phase 3)

The scheduler is built to `SCHEDULER_DESIGN.md` as binding policy. This note records the
few places the design left a decision to the implementation, and how each was resolved.
Code: `api/app/scheduler/` — `policy.py` (§4 ordering), `capability.py` (§3 buckets),
`assembly.py` (§6/§6.1/§7), `service.py` (orchestration + the operator confirm). Tests:
`api/tests/test_scheduler.py` (the §9 gate). Stance held throughout: **the scheduler
proposes; a human confirms; nothing auto-starts a physical machine.**

## Where the design was interpreted

1. **Printer availability keys on human-updated `Printer.status` — no telemetry (§5).**
   The design's no-preemption rule is specific: a Build that is *Printing* is never
   interrupted. So a printer is "untouchable" only when `status == printing`. Proposals
   are emitted only for printers the operator has marked `idle`. A printer that is `idle`
   but still holds a prior Build in a *post-print* stage (e.g. SLS cooldown, SLA wash) is
   treated as **available** — its running Build is surfaced as information, not used to
   auto-block. This honours "no faked telemetry": the operator's status is the truth, and
   the scheduler only proposes (the human won't confirm-start until the chamber/plate is
   actually clear). `confirm_proposal` re-checks `status == idle`.

2. **"Same (or swap-compatible) material" → one material per plate (§6).** A single Build
   loads one material, so a batch requires an **identical `material_pref` spec**. "Swap"
   refers to swapping the *printer's loaded* material to the batch's material; eligibility
   allows that (`allow_swaps`, default on) and each affected Job/proposal is flagged
   `needs_swap`. Mixing two different materials on one plate is never batched.

3. **Build-volume fit allows axis-aligned rotation (§3).** Fit compares the *sorted* part
   bbox dims to the *sorted* printer volume dims, so a part that fits in any axis
   orientation is eligible. A part with **unknown bbox** is assumed to fit (informs, never
   blocks on missing data) and noted as such.

4. **Material annotation aggregates stock by spec (§7).** Projected consumption (sum of the
   Jobs' slicer estimates) is compared to the **total `qty_remaining` summed across all
   lots of that spec**. `low_material` (the de-prioritization signal) fires when the build
   would run short **or** stock is below any same-spec `reorder_threshold` (R6: an unset
   threshold never warns). Short builds are still proposable; low-material proposals are
   sorted later — `sort(key=(low_material, shortfall, printer_id))` — never excluded.

5. **Age-boost lifts exactly one tier (§4.1).** Derived from `Job.queued_at` (R5), never
   stored; after `age_boost_hours` (default 72h) a Job's effective priority rises one tier,
   surfaced as `boosted` with a human reason ("low→normal (age-boosted, waited 3d)").
   Toggleable via `age_boost_enabled`.

6. **The "Queued" set (§2) = `queue_state == queued AND build_id IS NULL AND not
   terminal`.** Submitted (not yet triaged) and scheduled (already assigned) Jobs are
   excluded. This is also why a confirmed Job drops out of the next schedule — no
   double-scheduling.

7. **One proposal per idle printer = the immediate next Build.** Batching off → the top
   Job (one Job per Build); batching on → the first-fit-by-footprint-area batch. "Edit" and
   "dismiss" are console operations: edit calls `confirm_proposal` with the operator's
   chosen Job subset; dismiss simply never confirms.

8. **`MATERIAL_REQUIREMENTS` is a small data table** (`PA12-CF → enclosed`,
   `TPU → direct_drive`), matched against the `Printer.capabilities` JSON bag, plus an
   optional `capabilities["materials"]` allowlist. Adding a constraint = adding a row.

## Honest limits (as the design demands)

- **No 3D nesting (§6.1).** Batching is greedy first-fit by bounding-box **footprint area**
  with a fill-% cap (default 80%) — the anchor Job is always included; later same-material
  Jobs are added while within the cap. It is not a true 3D packer (no rotation/height
  stacking); a real nester is a documented future seam.
- **Estimates are slicer-grade.** Material projections come from parsed slicer estimates
  and are labelled as such; never implied as measured.
- **The scheduler never starts anything.** `build_schedule` is read-only. `confirm_proposal`
  is the sole mutator and runs only on explicit operator action; it sets the printer to
  `printing` as a human-updated status.

## §9 gate — all green (`pytest`, 39 passing total)

1. capability partition — a Job lands only in buckets it can physically run in.
2. ordering + age-boost — priority → deadline → age → id, boost fires at threshold.
3. no-preemption — a Critical arrival never interrupts a Printing Build; goes front-of-next-up.
4. build assembly — compatible Jobs group; different material / oversize don't; fill-cap holds.
5. material annotation — shortfall flagged but the Build is still proposable.
6. determinism — same inputs → same order (id tie-break).
   (plus: swap-eligibility toggle, batching-off one-per-build, fits-stock note, operator confirm.)
