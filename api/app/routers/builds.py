"""Build transition endpoints (operator). Each wraps an engine op; the endpoint owns the
transaction (one commit persists the StageEvent + recomputed column + any on_done txn)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import fulfillment
from .. import stage_engine as engine
from ..deps import get_db, require_operator
from ..models import Build, User
from ..schemas import AdvanceIn, NoteIn, ReasonIn
from ..serialize import build_out

router = APIRouter(prefix="/api/builds", tags=["builds"])


def _get(db, build_id) -> Build:
    b = db.get(Build, build_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    return b


@router.get("")
def list_builds(db: Session = Depends(get_db), op: User = Depends(require_operator)):
    return [build_out(b) for b in db.scalars(select(Build).order_by(Build.id.desc())).all()]


@router.get("/{build_id}")
def get_build(build_id: int, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    return build_out(_get(db, build_id), full=True)


@router.post("/{build_id}/advance")
def advance(build_id: int, body: AdvanceIn, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    b = _get(db, build_id)
    try:
        engine.advance(db, b, body.to_stage, actor=op, note=body.note)
    except engine.TransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    db.commit()
    return build_out(b, full=True)


@router.post("/{build_id}/hold")
def hold(build_id: int, body: NoteIn = NoteIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    b = _get(db, build_id)
    try:
        engine.hold(db, b, actor=op, note=body.note)
    except engine.TransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    db.commit()
    return build_out(b, full=True)


@router.post("/{build_id}/resume")
def resume(build_id: int, body: NoteIn = NoteIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    b = _get(db, build_id)
    try:
        engine.resume(db, b, actor=op, note=body.note)
    except engine.TransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    db.commit()
    return build_out(b, full=True)


@router.post("/{build_id}/fail")
def fail(build_id: int, body: ReasonIn = ReasonIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    b = _get(db, build_id)
    try:
        engine.fail(db, b, actor=op, reason=body.reason)
    except engine.TransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    for j in b.jobs:
        if j.terminal_status is None:
            fulfillment.notify_failed(db, ticket=j.ticket, job=j, reason=body.reason)
    db.commit()
    return build_out(b, full=True)


@router.post("/{build_id}/cancel")
def cancel(build_id: int, body: NoteIn = NoteIn(), db: Session = Depends(get_db), op: User = Depends(require_operator)):
    b = _get(db, build_id)
    try:
        engine.cancel(db, b, actor=op, note=body.note)
    except engine.TransitionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    db.commit()
    return build_out(b, full=True)
