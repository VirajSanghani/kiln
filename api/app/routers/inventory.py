"""Inventory: materials CRUD + event-sourced transactions + the warning set (operator)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import recompute_material_qty
from ..deps import get_db, require_operator
from ..enums import DryingState, InventoryReason, MaterialKind
from ..inventory import material_warnings
from ..models import InventoryTxn, Material, User
from ..schemas import MaterialCreateIn, TxnIn
from ..serialize import material_out

router = APIRouter(prefix="/api", tags=["inventory"])


def _get(db, material_id) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "material not found")
    return m


@router.get("/materials")
def list_materials(db: Session = Depends(get_db), op: User = Depends(require_operator)):
    return [material_out(m) for m in db.scalars(select(Material).order_by(Material.id)).all()]


@router.get("/materials/{material_id}")
def get_material(material_id: int, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    return material_out(_get(db, material_id))


@router.post("/materials")
def create_material(body: MaterialCreateIn, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    m = Material(
        kind=MaterialKind(body.kind), spec=body.spec, color=body.color, unit=body.unit,
        reorder_threshold=body.reorder_threshold, lot=body.lot,
        opened_date=date.fromisoformat(body.opened_date) if body.opened_date else None,
        shelf_life_days=body.shelf_life_days,
        drying_state=DryingState(body.drying_state) if body.drying_state else None,
        virgin_qty=body.virgin_qty, used_qty=body.used_qty, qty_remaining=0.0,
    )
    db.add(m)
    db.flush()
    if body.qty:
        # initial stock recorded as a restock txn so qty_remaining reconciles from events
        db.add(InventoryTxn(material_id=m.id, delta=body.qty, reason=InventoryReason.restock,
                            at=datetime.now(timezone.utc), actor_id=op.id, note="initial stock"))
        db.flush()
        recompute_material_qty(m)
    db.commit()
    return material_out(m)


def _apply_txn(db, material, *, delta, reason, actor, note):
    db.add(InventoryTxn(material_id=material.id, delta=delta, reason=reason,
                        at=datetime.now(timezone.utc), actor_id=actor.id, note=note))
    db.flush()
    recompute_material_qty(material)   # same transaction as the txn
    db.commit()


@router.post("/materials/{material_id}/restock")
def restock(material_id: int, body: TxnIn, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    m = _get(db, material_id)
    _apply_txn(db, m, delta=abs(body.delta), reason=InventoryReason.restock, actor=op, note=body.note)
    return material_out(m)


@router.post("/materials/{material_id}/adjust")
def adjust(material_id: int, body: TxnIn, db: Session = Depends(get_db), op: User = Depends(require_operator)):
    m = _get(db, material_id)
    _apply_txn(db, m, delta=body.delta, reason=InventoryReason.adjust, actor=op, note=body.note)
    return material_out(m)


@router.get("/inventory/warnings")
def warnings(db: Session = Depends(get_db), op: User = Depends(require_operator)):
    today = date.today()
    out = []
    for m in db.scalars(select(Material).order_by(Material.id)).all():
        w = material_warnings(m, today)
        if w:
            out.append({"material_id": m.id, "spec": m.spec, "warnings": w})
    return out
