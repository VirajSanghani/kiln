# KILN — Operator Wireframes (Phase 0)

Rough wireframes for the **three core operator screens**, drawn *before* data modeling so
the schema serves the real UI (not speculation). Aesthetic is Quiet Utility (Fraunces
headings, JetBrains Mono data, stone/amber). These are layout + data intent, not pixels.

The back half of this doc — **Pressure-test** — runs the four binding resolutions
(esp. #1 status derivation and #2 recipe shape) against these screens and flags exactly
what the model must provide before Phase 1. That is the real output of this exercise.

---

## Screen 1 — Scheduler / Queue Board (process-aware)

The scheduler PROPOSES; the operator DISPOSES. Left: capability buckets (per printer /
printer class) with ordered next-up + the *reason* the top job is first. Right: proposed
Builds to confirm/edit/dismiss. Top: per-process batching toggles with the tradeoff stated.

```
┌ KILN · Queue Board ───────────────────────────── operator: rk ─ [Material] [Fleet] [Dash] ┐
│ Batching:  FDM [ off ]   SLA [ off ]   SLS [ ON ]   MJF [ ON ]    (ON = group same-material,│
│            higher throughput / lower fairness · SLS·MJF default ON: don't waste a powder bed)│
├──────────────────────── CAPABILITY BUCKETS ─────────────┬──────── PROPOSED BUILDS ─────────┤
│ ▌Prusa-MK4 #1   FDM · loaded PETG-grey · IDLE           │ ◇ Build proposal  B-prop-7        │
│   next up:                                               │   FDM · Prusa-MK4 #1 · PETG-grey │
│   1. J-241  bracket v3      Critical · due 6/5  ★why     │   jobs: J-241, J-247, J-251      │
│      └ reason: Critical > High; earliest deadline       │   plate fill: 78%  (3 parts)     │
│   2. J-247  mount           High · due 6/6              │   material: PETG 62g → 138g left │
│   3. J-251  clip x4         Normal · no deadline        │            "fits stock ✓"        │
│   4. J-219  spacer          Low · boosted ⚡ (waited 3d) │   [ Confirm & start ] [edit] [✕] │
│                                                         │ ──────────────────────────────  │
│ ▌Form3 #1      SLA · loaded ClearV4 · PRINTING ⏵        │ ◇ Build proposal  B-prop-8        │
│   (running B-118, ~2h13m left · no preemption)          │   SLS · EOS-P1 · PA12            │
│   next up:                                               │   jobs: J-260..J-268 (9 parts)   │
│   1. J-255  lens housing    Normal · due 6/7            │   bed fill: 64% (cap 80%)        │
│                                                         │   material: PA12 410g → SHORT-30g│
│ ▌EOS-P1        SLS · loaded PA12 · IDLE                 │            ⚠ flagged, still ok   │
│   next up (batched):                                     │   refresh: 30% fresh / 70% used  │
│   1. J-260 gearset … +8 more  (see proposal B-prop-8)   │   [ Confirm & start ] [edit] [✕] │
└─────────────────────────────────────────────────────────┴──────────────────────────────────┘
```

Data this screen consumes: per-printer `process / loaded_material / status / capabilities`;
per-Job `priority / deadline / age(created_at) / process / bbox`; computed **ordering reason**
and **age-boost** flag; proposed Build groupings with **projected material vs stock** and
**fill %**. Running printers show "no preemption" + remaining estimate (slicer est.).

---

## Screen 2 — Ticket + Build Detail (with stage timeline)

One ticket, its FileVersion chain, the Build it currently rides, and the Build's stage
timeline. Per-Job rows show **derived** status; the timeline merges the recipe (expected
stages) with StageEvents (actuals: when, who).

```
┌ Ticket T-241 · "motor bracket" ──────────────── requester: ana · status: Printing ─────────┐
│ process: FDM   material pref: PETG   priority: Critical   deadline: 2026-06-05              │
├ Files (version chain) ──────────────────────────────────────────────────────────────────── │
│   v1  bracket.stl     slicer est 1h40m · 21g (PrusaSlicer)   — superseded                   │
│   v2  bracket.stl     slicer est 1h52m · 23g (PrusaSlicer)   — failed on B-110 (warp)       │
│ ▸ v3  bracket.stl     slicer est 1h48m · 22g (PrusaSlicer)   — PRINTING on B-117  ← current │
├ Current Build  B-117 ── Prusa-MK4 #1 · FDM · PETG-grey ──────────────────────────────────── │
│  Stage timeline (recipe: FDM):                                                              │
│   [Printing]──▶[Support removal]──▶[QC]──▶[Done]      side: Failed · On-hold · Cancelled    │
│    active        active            active   (term)                                          │
│    ✔ 14:02 rk    ● current         ◦ —      ◦ —                                              │
│                                                                                             │
│  Jobs on this Build (status derived from Build stage unless a terminal override is set):    │
│   J-241  T-241 bracket   → Printing        (inherits Build stage)                           │
│   J-247  T-247 mount     → Printing        (inherits Build stage)                           │
│   J-251  T-251 clip      → QC-rejected ✗    (terminal override · part warped) [requeue]      │
├ Activity (StageEvent log — truth of record) ──────────────────────────────────────────────  │
│   14:02  B-117  Queued → Printing      by rk   "plate loaded"                               │
│   13:40  B-117  assembled (J-241,247,251)      by scheduler→rk confirm                      │
└─────────────────────────────────────────────────────────────────────────────────────────── ┘
```

Data this screen consumes: Ticket fields + **ordered FileVersion chain** (each with slicer
est + which Build it printed on + outcome); the Job's **pinned FileVersion** (which version
actually printed); the Build's **current stage** + recipe (for the expected timeline);
**StageEvent** log (timestamps + actor) for the actuals; per-Job **terminal override** +
per-part QC outcome for derived status.

---

## Screen 3 — Material Shelf

Inventory **informs, never blocks**. Every warning here is a derived annotation, not a gate.

```
┌ KILN · Material Shelf ───────────────────────────────────────────── [+ Restock] [adjust] ──┐
│ kind     spec / color        remaining     lot / opened       warnings                       │
├──────────────────────────────────────────────────────────────────────────────────────────  │
│ filament PETG · grey         180 g         #A12 · 41d ago     —                               │
│ filament PA12-CF · black     420 g         #C7  · 12d ago     ⚠ needs drying (last 30d)       │
│ filament TPU · clear          90 g         #T3  · 60d ago     ⚠ low stock (< 150g)            │
│ resin    Clear V4            240 mL        #R9  · 5d ago      ⚠ shelf life: 25d left          │
│ resin    Tough 2000           60 mL        #R4  · 88d ago     ⚠ low · ⚠ shelf life: EXPIRED   │
│ powder   PA12 (SLS)        1,820 g virgin  blend 30/70        refresh ratio ok (≥30% fresh)   │
│                              640 g used                                                       │
│ agent    MJF fusing          1.1 L         #F2               —                               │
├──────────────────────────────────────────────────────────────────────────────────────────  │
│ Recent InventoryTxn:  -62g PETG (B-117 done)  ·  +1000g PA12 (restock)  ·  -410g PA12 (B-114)│
└─────────────────────────────────────────────────────────────────────────────────────────── ┘
```

Data this screen consumes: per-Material `kind / spec / color / qty_remaining / unit / lot /
opened_date`; filament `drying_state`; powder `virgin/used split` (→ refresh ratio);
optional `reorder_threshold` (for the low-stock warning); the **InventoryTxn** log.

---

## Pressure-test — do these screens want data the model wouldn't naturally provide?

Checked the screens against the four binding resolutions. Verdict: the resolutions hold,
with **one real gap** (status derivation needs a third clause), a handful of **refinements**
to bake into Phase 1, and several **confirmations**.

### Resolution #2 — recipe shape `{name, type(active|passive), allowed_next[]}` + universal side-transitions

- **CONFIRMED — one structure, three consumers.** The same recipe drives (a) stage-engine
  validation (`allowed_next`), (b) the Screen 2 timeline (ordered list = the left→right
  spine; `type` colours active vs passive), and (c) the future dashboard utilization
  metric (`type=active` time = machine/operator busy; `passive` = elapsing). The shape is
  coherent across all three. Keep it.

- **REFINEMENT R1 — the recipe owns Printing→Done; the pre-Build spine sits outside it.**
  The lifecycle `Submitted → Queued → Scheduled` happens *before any Build exists* (Screen 1
  shows these Jobs). The recipe should therefore start at **Printing** (type active) and run
  to **Done**, e.g. FDM = `Printing → Support removal → QC → Done`. The stage engine drives
  the Build from Printing onward; the pre-Build Job states are the universal spine handled by
  the ticket/scheduler layer, not the recipe engine. Draw this boundary explicitly in
  `docs/data-model.md`.

- **REFINEMENT R2 — mark the terminal stage.** The timeline must know which stage ends the
  run (to render "Done" and to let the dashboard compute completion). Cleanest: **terminal =
  the stage whose `allowed_next` is empty** (no new field), with `Done` being a real stage
  def. Entry stage = `stages[0]`. State this convention so it isn't reinvented.

- **CONFIRMED — optional/branching stages fit.** MJF's optional `(Dye)` is just
  `Depowder.allowed_next = [Dye, QC]` (skip allowed). The **ordered list** gives display
  order; **`allowed_next`** gives the legal-edge graph. List ≠ strict line, and that's fine —
  the two concerns are intentionally separate.

- **CONFIRMED — side-transitions are universal, not per-recipe.** `Failed / On-hold /
  Cancelled` are available from any stage and live outside the recipe's `allowed_next`
  (Screen 2 shows them as the right-hand deviation set). Re-queue from Failed re-enters the
  pre-Build spine. Matches the lifecycle in the build plan.

- **NOTE — recipe gives the skeleton, StageEvent gives the actuals.** Timestamps + actor on
  the timeline come from the append-only `StageEvent` log, not the recipe. The screen *merges*
  them. No conflict; just make sure StageEvent records `(build_id, from, to, actor, at, note)`.

### Resolution #1 — status derivation

- **GAP G1 (must fix before Phase 1) — derivation needs a THIRD clause for pre-Build Jobs.**
  As written, a Job's status is "terminal override, ELSE inherited from its Build's current
  stage." But Screen 1 is full of Jobs that are **Queued / Scheduled with no Build yet** —
  there is nothing to inherit from. The complete rule the screens require:

  > **Job effective status =**
  > 1. its **terminal override** if set (`Failed` / `QC-rejected` / `Cancelled`), else
  > 2. if assigned to a Build: **inherited from the Build's current stage**, else
  > 3. its own **pre-Build queue state** (`Submitted` / `Queued` / `Scheduled`).

  Storage implied: `Job.terminal_status` (nullable) + `Job.queue_state` (pre-Build) +
  `Job.build_id` (nullable) + `Build.current_stage`. Write the three-clause rule verbatim
  into `docs/data-model.md` (the resolution said "don't invent a variant" — this isn't a
  variant, it's the missing clause the original assumed a Build always exists).

- **CONFIRMED — per-part QC divergence works via the terminal override.** Screen 2 shows a
  Build at a later stage while one of its Jobs is `QC-rejected`. Clause 1 (terminal override)
  lets a single Job diverge while the Build proceeds to Done for the passing Jobs. Needs a
  per-Job QC outcome field feeding the override. Exactly what resolution #1 provides.

- **REFINEMENT R3 — a Job must pin the FileVersion it printed.** Screen 2's version chain
  shows "v2 failed on B-110, v3 printing on B-117." So "which version printed" lives at the
  **Job** level (`Job.file_version_id`), distinct from `Ticket.current_file_version_id`. The
  build plan already says FileVersion records "which version printed" — this nails *where*.

- **REFINEMENT R4 — define "latest" for ticket status precisely.** Resolution #1: a re-printed
  ticket "shows the latest." Make it deterministic: **ticket status follows the Job with the
  greatest `created_at`** (the most recent attempt). Single-Job ticket trivially mirrors its
  one Job. State the tie-break so the UI and any test agree.

- **REFINEMENT R5 — pre-Build Jobs need `created_at`/`queued_at` for age + boost.** Screen 1's
  "boosted ⚡ (waited 3d)" and the age tie-break (`SCHEDULER_DESIGN.md` §4) are computed from
  the Job's queue-entry time. The age-boost is a **derived annotation at scheduling time**, not
  a stored status. Ensure the timestamp exists on Job from Phase 1.

### Resolutions #3 & #4 (no screen impact)

- **#3 Auth (username/password, operator|requester):** the screens are role-gated (operator
  console here; requester portal is Phase 5). Minimal auth is sufficient — no screen needs
  more. Complexity budget stays on the scheduler.
- **#4 Naming:** "KILN" is a working-title wordmark only (masthead). Nothing is gated on it.

### Inventory screen — confirmations + one small add

- **CONFIRMED** the warning set (low stock / shelf-life / drying / powder-refresh) maps onto
  the Material fields already named in the build plan (`qty_remaining`, `unit`, `lot`,
  `opened_date`, filament `drying_state`, powder `virgin/used` split). All warnings are
  **derived annotations**, never gates (inventory informs, never blocks).
- **REFINEMENT R6 — add an optional `reorder_threshold` per material** (or per kind) so
  "low stock (< 150g)" has a defined source rather than a magic constant.

---

## Carry-forward into Phase 1 (data model)

1. **G1** — write the three-clause Job-status rule (above) verbatim in `docs/data-model.md`.
2. **R1/R2** — recipe spans Printing→Done; pre-Build spine is separate; terminal = empty
   `allowed_next`; entry = `stages[0]`.
3. **R3** — `Job.file_version_id` pins the printed version (distinct from the ticket's current).
4. **R4** — ticket status follows latest Job by `created_at`.
5. **R5** — Job carries a queue-entry timestamp; age-boost is derived, not stored.
6. **R6** — optional `reorder_threshold` on Material.
7. StageEvent shape `(build_id, from_stage, to_stage, actor, at, note)`; InventoryTxn shape
   `(material_id, build_id?, delta, reason, at, actor)` — both append-only, with the mutable
   `current_stage` / `qty_remaining` written in the **same transaction** (pragmatic audit).
