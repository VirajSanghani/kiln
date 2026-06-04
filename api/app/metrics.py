"""Ops dashboard metrics — EVERY figure derives from a real query over real data.

No placeholders. Each KPI is framed with context (§8 of DESIGN_LANGUAGE.md): a real
trend vs the prior period where a time basis exists, a clearly-labelled target where it
does not, or an honest "no prior-period data" when the prior window is empty. A metric that
can't be computed returns value=None with needs_more_data=True. Each section carries the
`query` string that backs it (traceability — see docs/ui.md).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import recipes
from .derivation import job_effective_status
from .enums import BuildStatus, InventoryReason, PrinterStatus
from .models import Build, InventoryTxn, Job, Printer, StageEvent

WINDOW_DAYS = 14
SUCCESS_TARGET_PCT = 90.0  # stated lab target (a goal, NOT a measurement — labelled as such)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def throughput(session, now):
    builds = session.scalars(
        select(Build).where(Build.status == BuildStatus.completed, Build.completed_at.is_not(None))
    ).all()
    w_start = now - timedelta(days=WINDOW_DAYS)
    p_start = now - timedelta(days=2 * WINDOW_DAYS)
    by_day: dict[str, int] = defaultdict(int)
    in_window = prior = 0
    for b in builds:
        c = _aware(b.completed_at)
        if c >= w_start:
            by_day[c.date().isoformat()] += 1
            in_window += 1
        elif c >= p_start:
            prior += 1
    days = [(w_start + timedelta(days=i)).date().isoformat() for i in range(WINDOW_DAYS + 1)]
    return {
        "completed_total": len(builds),
        "completed_in_window": in_window,
        "prior_window": prior,
        "delta": in_window - prior,
        "window_days": WINDOW_DAYS,
        "by_day": [{"date": d, "count": by_day.get(d, 0)} for d in days],
        "needs_more_data": len(builds) == 0,
        "query": "builds WHERE status=completed, bucketed by completed_at date over the window",
    }


def fleet(session):
    printers = session.scalars(select(Printer).order_by(Printer.id)).all()
    printing = occupied = available = down = 0
    for p in printers:
        running = session.scalars(
            select(Build).where(Build.printer_id == p.id, Build.status == BuildStatus.running)
        ).first()
        occ = running is not None and recipes.occupies_machine(running.process, running.current_stage)
        if p.status in (PrinterStatus.down, PrinterStatus.maintenance):
            down += 1
        elif p.status == PrinterStatus.printing:
            printing += 1
        elif occ:
            occupied += 1
        else:
            available += 1
    total = len(printers)
    in_use = printing + occupied
    return {
        "total": total, "printing": printing, "occupied": occupied,
        "available": available, "down": down, "in_use": in_use,
        "utilization_pct": round(100.0 * in_use / total, 1) if total else None,
        "needs_more_data": total == 0,
        "query": "printers joined to their running Build; in-use = printing OR occupies_machine stage",
    }


def success(session):
    delivered = failed = rejected = cancelled = 0
    for j in session.scalars(select(Job)).all():
        s = job_effective_status(j)
        delivered += s == "done"
        failed += s == "failed"
        rejected += s == "qc_rejected"
        cancelled += s == "cancelled"
    finished = delivered + failed + rejected
    return {
        "delivered": delivered, "failed": failed, "rejected": rejected, "cancelled": cancelled,
        "rate_pct": round(100.0 * delivered / finished, 1) if finished else None,
        "target_pct": SUCCESS_TARGET_PCT,
        "needs_more_data": finished == 0,
        "query": "jobs by derived status; rate = done / (done+failed+qc_rejected)",
    }


def queue_wait(session, now):
    events = session.scalars(
        select(StageEvent).where(StageEvent.to_stage == "printing", StageEvent.build_id.is_not(None))
    ).all()
    first_print: dict[int, datetime] = {}
    for e in events:
        at = _aware(e.at)
        if e.build_id not in first_print or at < first_print[e.build_id]:
            first_print[e.build_id] = at

    w_start = now - timedelta(days=WINDOW_DAYS)
    p_start = now - timedelta(days=2 * WINDOW_DAYS)
    all_waits, win_waits, prior_waits = [], [], []
    for j in session.scalars(select(Job).where(Job.build_id.is_not(None), Job.queued_at.is_not(None))).all():
        start = first_print.get(j.build_id)
        if start is None:
            continue
        h = (start - _aware(j.queued_at)).total_seconds() / 3600.0
        if h < 0:
            continue
        all_waits.append(h)
        if start >= w_start:
            win_waits.append(h)
        elif start >= p_start:
            prior_waits.append(h)

    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    return {
        "avg_hours": avg(all_waits), "sample": len(all_waits),
        "window_avg": avg(win_waits), "window_sample": len(win_waits),
        "prior_avg": avg(prior_waits), "prior_sample": len(prior_waits),
        "needs_more_data": len(all_waits) == 0,
        "query": "per job: (build's first 'printing' StageEvent.at) - job.queued_at; averaged",
    }


def burn(session, now):
    w_start = now - timedelta(days=WINDOW_DAYS)
    p_start = now - timedelta(days=2 * WINDOW_DAYS)
    consumed: dict[str, dict] = {}
    in_window = prior = 0.0
    for txn in session.scalars(select(InventoryTxn).where(InventoryTxn.reason == InventoryReason.consume)).all():
        spec = txn.material.spec
        row = consumed.setdefault(spec, {"spec": spec, "consumed": 0.0, "unit": txn.material.unit})
        row["consumed"] += -txn.delta
        at = _aware(txn.at)
        if at and at >= w_start:
            in_window += -txn.delta
        elif at and at >= p_start:
            prior += -txn.delta
    projected: dict[str, float] = defaultdict(float)
    for b in session.scalars(select(Build).where(Build.status == BuildStatus.running)).all():
        if b.material is None:
            continue
        for j in b.jobs:
            fv = j.file_version
            if fv and fv.est_material_qty is not None:
                projected[b.material.spec] += fv.est_material_qty
    rows = sorted(consumed.values(), key=lambda r: r["consumed"], reverse=True)
    return {
        "by_material": [{**r, "consumed": round(r["consumed"], 3)} for r in rows],
        "consumed_in_window": round(in_window, 3), "prior_window": round(prior, 3),
        "projected_est": [{"spec": k, "qty": round(v, 3)} for k, v in sorted(projected.items())],
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
        "burn": burn(session, now),
    }
