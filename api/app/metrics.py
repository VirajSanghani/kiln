"""Ops dashboard metrics — EVERY figure derives from a real query over real data.

No placeholders. If a metric can't be computed from the logs it returns value=None with
needs_more_data=True, and the UI labels it "needs more data". Each section carries a
`query` string describing exactly what backs it (traceability — see docs/ui.md).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import recipes
from .derivation import job_effective_status
from .enums import BuildStatus, InventoryReason, PrinterStatus
from .models import Build, InventoryTxn, Job, Printer, StageEvent

THROUGHPUT_WINDOW_DAYS = 14


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def throughput(session, now):
    builds = session.scalars(
        select(Build).where(Build.status == BuildStatus.completed, Build.completed_at.is_not(None))
    ).all()
    window_start = now - timedelta(days=THROUGHPUT_WINDOW_DAYS)
    by_day: dict[str, int] = defaultdict(int)
    in_window = 0
    for b in builds:
        c = _aware(b.completed_at)
        if c >= window_start:
            by_day[c.date().isoformat()] += 1
            in_window += 1
    days = [(window_start + timedelta(days=i)).date().isoformat() for i in range(THROUGHPUT_WINDOW_DAYS + 1)]
    series = [{"date": d, "count": by_day.get(d, 0)} for d in days]
    return {
        "completed_total": len(builds),
        "completed_in_window": in_window,
        "window_days": THROUGHPUT_WINDOW_DAYS,
        "by_day": series,
        "needs_more_data": len(builds) == 0,
        "query": "builds WHERE status=completed; bucketed by completed_at date over the window",
    }


def fleet(session):
    printers = session.scalars(select(Printer).order_by(Printer.id)).all()
    rows = []
    printing = occupied = available = down = 0
    for p in printers:
        running = session.scalars(
            select(Build).where(Build.printer_id == p.id, Build.status == BuildStatus.running)
        ).first()
        occ = running is not None and recipes.occupies_machine(running.process, running.current_stage)
        if p.status in (PrinterStatus.down, PrinterStatus.maintenance):
            state, down = "down", down + 1
        elif p.status == PrinterStatus.printing:
            state, printing = "printing", printing + 1
        elif occ:
            state, occupied = "occupied", occupied + 1
        else:
            state, available = "available", available + 1
        rows.append({
            "id": p.id, "name": p.name, "process": p.process.value, "status": p.status.value,
            "state": state, "loaded_material": p.loaded_material.spec if p.loaded_material else None,
            "running_build_id": running.id if running else None,
            "running_stage": running.current_stage if running else None,
        })
    total = len(printers)
    in_use = printing + occupied
    return {
        "total": total, "printing": printing, "occupied": occupied,
        "available": available, "down": down,
        "utilization_pct": round(100.0 * in_use / total, 1) if total else None,
        "printers": rows,
        "needs_more_data": total == 0,
        "query": "printers joined to their running Build; in-use = printing OR occupies_machine stage",
    }


def success(session):
    jobs = session.scalars(select(Job)).all()
    delivered = failed = rejected = cancelled = 0
    for j in jobs:
        s = job_effective_status(j)
        if s == "done":
            delivered += 1
        elif s == "failed":
            failed += 1
        elif s == "qc_rejected":
            rejected += 1
        elif s == "cancelled":
            cancelled += 1
    finished = delivered + failed + rejected   # cancellations excluded (not a quality outcome)
    return {
        "delivered": delivered, "failed": failed, "rejected": rejected, "cancelled": cancelled,
        "rate_pct": round(100.0 * delivered / finished, 1) if finished else None,
        "needs_more_data": finished == 0,
        "query": "jobs by derived status; rate = done / (done+failed+qc_rejected)",
    }


def queue_wait(session, now):
    # first 'printing' build-level event per build
    events = session.scalars(
        select(StageEvent).where(StageEvent.to_stage == "printing", StageEvent.build_id.is_not(None))
    ).all()
    first_print: dict[int, datetime] = {}
    for e in events:
        at = _aware(e.at)
        if e.build_id not in first_print or at < first_print[e.build_id]:
            first_print[e.build_id] = at
    waits = []
    for j in session.scalars(select(Job).where(Job.build_id.is_not(None), Job.queued_at.is_not(None))).all():
        start = first_print.get(j.build_id)
        if start is not None:
            h = (start - _aware(j.queued_at)).total_seconds() / 3600.0
            if h >= 0:
                waits.append(h)
    avg = round(sum(waits) / len(waits), 2) if waits else None
    return {
        "avg_hours": avg, "sample": len(waits),
        "needs_more_data": len(waits) == 0,
        "query": "per job: (build's first 'printing' StageEvent.at) - job.queued_at; averaged",
    }


def burn(session):
    consumed: dict[str, dict] = {}
    for txn in session.scalars(select(InventoryTxn).where(InventoryTxn.reason == InventoryReason.consume)).all():
        spec = txn.material.spec
        row = consumed.setdefault(spec, {"spec": spec, "consumed": 0.0, "unit": txn.material.unit})
        row["consumed"] += -txn.delta
    # projected (slicer est.) for in-flight builds
    projected: dict[str, float] = defaultdict(float)
    for b in session.scalars(select(Build).where(Build.status == BuildStatus.running)).all():
        if b.material is None:
            continue
        for j in b.jobs:
            fv = j.file_version
            if fv and fv.est_material_qty is not None:
                projected[b.material.spec] += fv.est_material_qty
    return {
        "by_material": [
            {**row, "consumed": round(row["consumed"], 3)} for row in consumed.values()
        ],
        "projected_est": [{"spec": k, "qty": round(v, 3)} for k, v in projected.items()],
        "needs_more_data": not consumed,
        "query": "sum(-delta) WHERE reason=consume, by material; projected = Σ slicer est. of running builds",
    }


def dashboard(session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "throughput": throughput(session, now),
        "fleet": fleet(session),
        "success": success(session),
        "queue_wait": queue_wait(session, now),
        "burn": burn(session),
    }
