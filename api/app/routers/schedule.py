"""Scheduler endpoints (operator): view the proposal, confirm one (the dispose step)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import fulfillment
from ..deps import get_db, require_operator
from ..enums import QueueState
from ..models import Job, Printer, User
from ..schemas import ConfirmIn
from ..scheduler import SchedulerConfig, build_schedule, confirm_proposal
from ..serialize import build_out

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule(
    fdm: bool | None = None, sla: bool | None = None,
    sls: bool | None = None, mjf: bool | None = None,
    age_boost_hours: float | None = None,
    db: Session = Depends(get_db), op: User = Depends(require_operator),
):
    from ..enums import ProcessType
    cfg = SchedulerConfig()
    overrides = {ProcessType.FDM: fdm, ProcessType.SLA: sla, ProcessType.SLS: sls, ProcessType.MJF: mjf}
    for proc, val in overrides.items():
        if val is not None:
            cfg.batching[proc] = val
    if age_boost_hours is not None:
        cfg.age_boost_hours = age_boost_hours
    return asdict(build_schedule(db, cfg))


@router.post("/confirm")
def confirm(body: ConfirmIn, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    printer = db.get(Printer, body.printer_id)
    if printer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "printer not found")
    jobs = [db.get(Job, jid) for jid in body.job_ids]
    if any(j is None for j in jobs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "one or more jobs not found")
    if not all(j.queue_state == QueueState.queued and j.build_id is None and j.terminal_status is None for j in jobs):
        raise HTTPException(status.HTTP_409_CONFLICT, "all jobs must be unassigned + queued")
    try:
        build = confirm_proposal(db, printer, jobs, actor=op, note=body.note)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    fulfillment.notify_started(db, build)
    db.commit()
    return build_out(build, full=True)
