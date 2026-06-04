"""Pydantic request bodies (JSON endpoints). Multipart endpoints use Form/File directly."""
from __future__ import annotations

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class AdvanceIn(BaseModel):
    to_stage: str
    note: str | None = None


class NoteIn(BaseModel):
    note: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class ConfirmIn(BaseModel):
    printer_id: int
    job_ids: list[int]
    note: str | None = None


class MaterialCreateIn(BaseModel):
    kind: str
    spec: str
    unit: str
    qty: float = 0.0
    color: str | None = None
    reorder_threshold: float | None = None
    lot: str | None = None
    opened_date: str | None = None       # ISO date
    shelf_life_days: int | None = None
    drying_state: str | None = None
    virgin_qty: float | None = None
    used_qty: float | None = None


class TxnIn(BaseModel):
    delta: float
    note: str | None = None
