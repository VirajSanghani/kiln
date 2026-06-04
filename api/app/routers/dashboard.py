"""Ops dashboard + fleet + a jobs list — read-only operator surfaces."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics
from ..deps import get_db, require_operator
from ..enums import BuildStatus, PrinterStatus
from ..models import Build, Printer, User

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), op: User = Depends(require_operator)):
    return metrics.dashboard(db)


@router.get("/printers")
def list_printers(db: Session = Depends(get_db), op: User = Depends(require_operator)):
    out = []
    for p in db.scalars(select(Printer).order_by(Printer.id)).all():
        running = db.scalars(
            select(Build).where(Build.printer_id == p.id, Build.status == BuildStatus.running)
        ).first()
        out.append({
            "id": p.id, "name": p.name, "process": p.process.value, "status": p.status.value,
            "build_volume": [p.build_volume_x, p.build_volume_y, p.build_volume_z],
            "loaded_material": p.loaded_material.spec if p.loaded_material else None,
            "capabilities": p.capabilities,
            "running_build_id": running.id if running else None,
            "running_stage": running.current_stage if running else None,
        })
    return out
