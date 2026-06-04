"""Pragmatic audit: fold the append-only logs and assert the mutable columns match.

The append-only `StageEvent` / `InventoryTxn` rows are the truth-of-record. The mutable
columns (`Build.current_stage/status`, `Job.queue_state/terminal_status`,
`Material.qty_remaining`) are written in the SAME transaction as their event, so they
should never drift. `reconcile_all` proves it: column == fold(events). Run it as

    python -m app.audit

It exits non-zero if anything has drifted (CI / cron / pre-deploy guard).

This is NOT full event-sourcing — we keep fast-read columns and guard them, rather than
rebuilding state from the log on every read. For this domain that is the right trade.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .db import SessionLocal
from .enums import BuildStatus, JobTerminalStatus, QueueState
from .recipes.registry import DONE, SIDE_STATES

QUEUE_TOKENS = {"submitted", "queued", "scheduled"}
TERMINAL_TOKENS = {"failed", "qc_rejected", "cancelled"}


# --------------------------------------------------------------------------------------
# Pure folds (operate on ordered lists of events; no DB)
# --------------------------------------------------------------------------------------
def fold_build(events) -> tuple[str | None, BuildStatus]:
    """Replay build-level events -> (current_stage, status).

    A side-state event sets the status overlay but leaves current_stage parked at its
    recipe position; a subsequent recipe-stage event (resume / advance) clears it.
    """
    current_stage: str | None = None
    status = BuildStatus.running
    for e in events:
        to = e.to_stage
        if to in SIDE_STATES:
            status = BuildStatus(to)            # on_hold / failed / cancelled
        elif to == DONE:
            current_stage = to
            status = BuildStatus.completed
        else:
            current_stage = to
            status = BuildStatus.running
    return current_stage, status


def fold_job_queue(events) -> QueueState:
    qs = QueueState.submitted
    for e in events:
        if e.to_stage in QUEUE_TOKENS:
            qs = QueueState(e.to_stage)
    return qs


def fold_job_terminal(events) -> JobTerminalStatus | None:
    t: JobTerminalStatus | None = None
    for e in events:
        if e.to_stage in TERMINAL_TOKENS:
            t = JobTerminalStatus(e.to_stage)
    return t


def fold_material_qty(txns) -> float:
    return round(sum(t.delta for t in txns), 6)


# --------------------------------------------------------------------------------------
# Same-transaction column writers (used by the seed; the Phase 2 engine will reuse these)
# --------------------------------------------------------------------------------------
def _ordered(events):
    return sorted(events, key=lambda e: (e.at, e.id or 0))


def recompute_build_columns(build) -> None:
    evs = _ordered([e for e in build.stage_events if e.job_id is None])
    build.current_stage, build.status = fold_build(evs)


def recompute_job_columns(job) -> None:
    q = _ordered([e for e in job.events if e.build_id is None and e.to_stage in QUEUE_TOKENS])
    o = _ordered([e for e in job.events if e.to_stage in TERMINAL_TOKENS])
    job.queue_state = fold_job_queue(q)
    job.terminal_status = fold_job_terminal(o)


def recompute_material_qty(material) -> None:
    material.qty_remaining = fold_material_qty(material.txns)


# --------------------------------------------------------------------------------------
# Reconcile (DB-backed assertions)
# --------------------------------------------------------------------------------------
@dataclass
class Discrepancy:
    entity: str
    id: int
    field: str
    column: object
    folded: object

    def __str__(self) -> str:
        return f"{self.entity}#{self.id}.{self.field}: column={self.column!r} != fold={self.folded!r}"


def reconcile_all(session) -> list[Discrepancy]:
    """Assert every mutable column equals the fold of its append-only events."""
    from sqlalchemy import select

    from .models import Build, InventoryTxn, Job, Material, StageEvent

    out: list[Discrepancy] = []

    # Builds
    for build in session.scalars(select(Build)).all():
        evs = session.scalars(
            select(StageEvent)
            .where(StageEvent.build_id == build.id, StageEvent.job_id.is_(None))
            .order_by(StageEvent.at, StageEvent.id)
        ).all()
        stage, status = fold_build(evs)
        if build.current_stage != stage:
            out.append(Discrepancy("Build", build.id, "current_stage", build.current_stage, stage))
        if build.status != status:
            out.append(Discrepancy("Build", build.id, "status", build.status, status))

    # Jobs
    for job in session.scalars(select(Job)).all():
        q_evs = session.scalars(
            select(StageEvent)
            .where(StageEvent.job_id == job.id, StageEvent.build_id.is_(None))
            .order_by(StageEvent.at, StageEvent.id)
        ).all()
        o_evs = session.scalars(
            select(StageEvent)
            .where(StageEvent.job_id == job.id, StageEvent.to_stage.in_(TERMINAL_TOKENS))
            .order_by(StageEvent.at, StageEvent.id)
        ).all()
        qs = fold_job_queue(q_evs)
        term = fold_job_terminal(o_evs)
        if job.queue_state != qs:
            out.append(Discrepancy("Job", job.id, "queue_state", job.queue_state, qs))
        if job.terminal_status != term:
            out.append(Discrepancy("Job", job.id, "terminal_status", job.terminal_status, term))

    # Materials
    for material in session.scalars(select(Material)).all():
        txns = session.scalars(
            select(InventoryTxn).where(InventoryTxn.material_id == material.id)
        ).all()
        folded = fold_material_qty(txns)
        if round(material.qty_remaining, 6) != folded:
            out.append(
                Discrepancy("Material", material.id, "qty_remaining", material.qty_remaining, folded)
            )

    return out


def main() -> int:
    with SessionLocal() as session:
        discrepancies = reconcile_all(session)
    if discrepancies:
        print(f"RECONCILE FAILED — {len(discrepancies)} discrepancy(ies):")
        for d in discrepancies:
            print(f"  - {d}")
        return 1
    print("RECONCILE OK — every mutable column matches fold(events).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
