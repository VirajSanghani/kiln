"""Tickets + file upload + slicer parsing."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import slicer, storage
from ..config import settings
from ..deps import get_current_user, get_db
from ..enums import Priority, ProcessType, UserRole
from ..models import FileVersion, Job, Ticket, User
from ..serialize import file_version_out, ticket_out

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _parse_estimate(content: bytes, slicer_summary: str | None):
    """Try the explicit summary first, else the file's own text (gcode). None if neither parses."""
    for text in (slicer_summary, content.decode("utf-8", errors="ignore")):
        if not text:
            continue
        try:
            return slicer.parse(text)
        except slicer.SlicerParseError:
            continue
    return None


def _add_file_version(db, ticket, *, file: UploadFile, content: bytes, slicer_summary,
                      bbox_x, bbox_y, bbox_z) -> FileVersion:
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file exceeds size cap")
    blob = storage.save_blob(content, original_filename=file.filename or "upload.bin")
    est = _parse_estimate(content, slicer_summary)
    next_no = 1 + max((fv.version_no for fv in ticket.file_versions), default=0)
    fv = FileVersion(
        ticket=ticket, version_no=next_no, filename=file.filename or "upload.bin",
        blob_key=blob["blob_key"], checksum=blob["checksum"], size_bytes=blob["size"],
        slicer_name=est.slicer_name if est else None,
        est_time_seconds=est.est_time_seconds if est else None,
        est_material_qty=est.est_material_qty if est else None,
        est_material_unit=est.est_material_unit if est else None,
        bbox_x=bbox_x, bbox_y=bbox_y, bbox_z=bbox_z,
    )
    db.add(fv)
    db.flush()
    ticket.current_file_version = fv     # newest version is current
    return fv


def _owned_or_operator(ticket, user):
    if user.role != UserRole.operator and ticket.requester_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your ticket")


@router.post("")
def create_ticket(
    title: str = Form(...),
    target_process: ProcessType = Form(...),
    priority: Priority = Form(Priority.normal),
    material_pref: str | None = Form(None),
    deadline: str | None = Form(None),
    slicer_summary: str | None = Form(None),
    bbox_x: float | None = Form(None),
    bbox_y: float | None = Form(None),
    bbox_z: float | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = Ticket(
        requester_id=user.id, title=title, target_process=target_process,
        material_pref=material_pref, priority=priority,
        deadline=date.fromisoformat(deadline) if deadline else None,
    )
    db.add(ticket)
    db.flush()
    content = file.file.read()
    _add_file_version(db, ticket, file=file, content=content, slicer_summary=slicer_summary,
                      bbox_x=bbox_x, bbox_y=bbox_y, bbox_z=bbox_z)
    db.add(Job(ticket=ticket))   # one Job in 'submitted' (queue it to enter scheduling)
    db.commit()
    return ticket_out(ticket, full=True)


@router.post("/{ticket_id}/files")
def add_file_version(
    ticket_id: int,
    slicer_summary: str | None = Form(None),
    bbox_x: float | None = Form(None),
    bbox_y: float | None = Form(None),
    bbox_z: float | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")
    _owned_or_operator(ticket, user)
    content = file.file.read()
    fv = _add_file_version(db, ticket, file=file, content=content, slicer_summary=slicer_summary,
                           bbox_x=bbox_x, bbox_y=bbox_y, bbox_z=bbox_z)
    db.commit()
    return file_version_out(fv)


@router.get("")
def list_tickets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Ticket).order_by(Ticket.created_at.desc())
    if user.role != UserRole.operator:
        q = q.where(Ticket.requester_id == user.id)   # requester sees only their own
    return [ticket_out(t) for t in db.scalars(q).all()]


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ticket not found")
    _owned_or_operator(ticket, user)
    return ticket_out(ticket, full=True)
