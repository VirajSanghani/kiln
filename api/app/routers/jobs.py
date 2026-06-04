"""Job endpoints: queue (submitted->queued) + per-Job terminal overrides."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import fulfillment
from .. import stage_engine as engine
from ..audit import recompute_job_columns
from ..deps import get_current_user, get_db, require_operator
from ..enums import QueueState, UserRole
from ..models import Job, StageEvent, User
from ..schemas import NoteIn, ReasonIn
from ..serialize import job_out

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get(db, job_id) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _get(db, job_id)
    if user.role != UserRole.operator and job.ticket.requester_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    return job_out(job)


@router.post("/{job_id}/queue")
def queue_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Move a submitted Job into the queue so the scheduler can see it. Owner or operator."""
    job = _get(db, job_id)
    if user.role != UserRole.operator and job.ticket.requester_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    if job.queue_state != QueueState.submitted or job.build_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {job.queue_state.value}, cannot queue")
    now = datetime.now(timezone.utc)
    e = StageEvent(from_stage=QueueState.submitted.value, to_stage=QueueState.queued.value, at=now, job=job)
    e.actor = user
    db.add(e)
    job.queued_at = now
    db.flush()
    recompute_job_columns(job)
    db.commit()
    return job_out(job)


@router.post("/{job_id}/reject")
def reject(job_id: int, body: NoteIn = NoteIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    job = _get(db, job_id)
    engine.reject_job(db, job, actor=op, note=body.note)
    fulfillment.notify_failed(db, ticket=job.ticket, job=job, reason=body.note or "rejected at QC")
    db.commit()
    return job_out(job)


@router.post("/{job_id}/fail")
def fail(job_id: int, body: ReasonIn = ReasonIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    job = _get(db, job_id)
    engine.fail_job(db, job, actor=op, reason=body.reason)
    fulfillment.notify_failed(db, ticket=job.ticket, job=job, reason=body.reason)
    db.commit()
    return job_out(job)


@router.post("/{job_id}/cancel")
def cancel(job_id: int, body: NoteIn = NoteIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    job = _get(db, job_id)
    engine.cancel_job(db, job, actor=op, note=body.note)
    db.commit()
    return job_out(job)
