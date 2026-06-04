"""ORM -> plain-dict serializers. Status fields are always the DERIVED values."""
from __future__ import annotations

from .derivation import build_effective_state, job_effective_status, ticket_status
from .inventory import material_warnings
from .recipes import recipe_for


def user_out(u):
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role.value}


def file_version_out(fv):
    return {
        "id": fv.id, "version_no": fv.version_no, "filename": fv.filename,
        "blob_key": fv.blob_key, "checksum": fv.checksum, "size_bytes": fv.size_bytes,
        "slicer_name": fv.slicer_name,
        "est_time_seconds": fv.est_time_seconds,
        "est_material_qty": fv.est_material_qty, "est_material_unit": fv.est_material_unit,
        "estimate_label": "slicer est." if fv.slicer_name else None,
        "bbox": [fv.bbox_x, fv.bbox_y, fv.bbox_z] if fv.bbox_x is not None else None,
        "created_at": fv.created_at.isoformat() if fv.created_at else None,
    }


def job_out(j):
    return {
        "id": j.id, "ticket_id": j.ticket_id, "build_id": j.build_id,
        "file_version_id": j.file_version_id,
        "status": job_effective_status(j),               # G1
        "queue_state": j.queue_state.value,
        "terminal_status": j.terminal_status.value if j.terminal_status else None,
        "qc_outcome": j.qc_outcome.value if j.qc_outcome else None,
        "fail_reason": j.fail_reason,
        "allocated_qty": j.allocated_qty, "allocated_unit": j.allocated_unit,
        "queued_at": j.queued_at.isoformat() if j.queued_at else None,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


def ticket_out(t, *, full=False):
    out = {
        "id": t.id, "title": t.title, "target_process": t.target_process.value,
        "material_pref": t.material_pref, "priority": t.priority.value,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "status": ticket_status(t),                      # R4
        "requester": user_out(t.requester),
        "current_file_version_id": t.current_file_version_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if full:
        out["file_versions"] = [file_version_out(fv) for fv in t.file_versions]
        out["jobs"] = [job_out(j) for j in t.jobs]
    return out


def _recipe_spine(process):
    return [{"name": s.name, "label": s.label, "type": s.type,
             "occupies_machine": s.occupies_machine, "allowed_next": list(s.allowed_next)}
            for s in recipe_for(process)]


def build_out(b, *, full=False):
    out = {
        "id": b.id, "printer_id": b.printer_id, "printer_name": b.printer.name if b.printer else None,
        "process": b.process.value, "current_stage": b.current_stage,
        "status": b.status.value, "effective_state": build_effective_state(b),
        "material_spec": b.material.spec if b.material else None,
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "jobs": [job_out(j) for j in b.jobs],
    }
    if full:
        out["recipe"] = _recipe_spine(b.process)
        out["timeline"] = [
            {"from": e.from_stage, "to": e.to_stage,
             "at": e.at.isoformat() if e.at else None,
             "actor": e.actor.username if e.actor else None, "note": e.note}
            for e in sorted((e for e in b.stage_events if e.job_id is None), key=lambda e: (e.at, e.id))
        ]
    return out


def material_out(m, today=None):
    return {
        "id": m.id, "kind": m.kind.value, "spec": m.spec, "color": m.color, "unit": m.unit,
        "qty_remaining": m.qty_remaining, "reorder_threshold": m.reorder_threshold,
        "lot": m.lot, "opened_date": m.opened_date.isoformat() if m.opened_date else None,
        "shelf_life_days": m.shelf_life_days,
        "drying_state": m.drying_state.value if m.drying_state else None,
        "virgin_qty": m.virgin_qty, "used_qty": m.used_qty,
        "warnings": material_warnings(m, today),
    }


def notification_out(n):
    return {
        "id": n.id, "kind": n.kind.value, "message": n.message, "read": n.read,
        "ticket_id": n.ticket_id, "job_id": n.job_id,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
