# KILN — Inventory (Phase 4)

**Inventory INFORMS, it NEVER BLOCKS.** It projects consumption, flags shortfalls and
shelf/drying/refresh conditions, and decrements on Build Done — but it never prevents
queuing, scheduling, or confirming a Build. Real labs override; the system trusts them.

Code: `app/inventory.py` (warnings), `app/fulfillment.py` (on-Done decrement),
`app/routers/inventory.py` (CRUD + txns), `app/audit.py` (reconcile).

## Event-sourced quantities
`InventoryTxn` is append-only truth-of-record; `Material.qty_remaining` is a fast-read
written in the **same transaction** as its txn. Invariant: `qty_remaining == Σ delta`
(reconciled by `app/audit.py`). Three reasons:
- `restock` (+) — new stock; the initial stock of a created material is itself a restock txn.
- `consume` (−) — written on Build Done (see below).
- `adjust` (±) — hand correction (spillage, recount), with a note.

`POST /api/materials/{id}/restock|adjust` add a txn and recompute the column atomically.

## On-Done decrement (the critical same-transaction path)
When a Build reaches **Done**, `stage_engine.advance` calls `fulfillment.on_build_done`
**before returning**, inside the endpoint's transaction:
1. project consumption = Σ of the Jobs' slicer estimates (the versions that printed);
2. write **one** `consume` `InventoryTxn` against the Build's material and
   `recompute_material_qty` (decrement once per Build);
3. allocate the share to each Job (`Job.allocated_qty`);
4. emit `ready_for_pickup` notifications for delivered Jobs.

The endpoint then commits **once** — the Done StageEvent, the column updates, and the
inventory txn ride a single commit. A crash between "mark done" and "decrement" is
impossible; if anything ever desynced, `python -m app.audit` (or `reconcile_all`) would
catch it (`qty_remaining != Σ delta`). Tested end-to-end: a 22 g print drops PETG 200 → 178
and reconcile stays clean.

## The warning set (derived annotations, never gates)
Computed per material by `material_warnings(material, today)`:

| Warning | Condition | Severity |
|---|---|---|
| **low_stock** | `reorder_threshold` set **and** `qty_remaining < threshold` (R6: unset ⇒ never warns) | warn |
| **shelf_life** (resin) | `opened_date + shelf_life_days` vs today: expired / ≤14d / ≤30d | critical / warn / info |
| **drying** (filament) | `drying_state == needs_drying` | warn |
| **powder_refresh** (powder) | virgin/used blend; fresh fraction `< 30%` warns, else info | warn / info |

`GET /api/inventory/warnings` returns them across the shelf; `GET /api/materials` embeds
each material's warnings. Example (seed): PA12-CF "needs drying", TPU "low stock 90g < 150g",
Clear V4 "shelf life: 25d left", Tough 2000 "low + EXPIRED 28d ago", PA12 "blend 74% fresh".

## Scheduler material awareness (recap, §7)
At proposal time the scheduler annotates projected consumption vs total same-spec stock —
"fits stock" or "short by Xg — flagged" — and **de-prioritizes** low-material proposals
without ever excluding them. See `docs/scheduler-notes.md`.

## Powder virgin/used — v1 limitation
`virgin_qty`/`used_qty` drive the refresh-ratio annotation, but the core reconcile invariant
is on the single `qty_remaining`. Per-stream (virgin vs used) transactional accounting is a
documented future refinement, not built in v1.
