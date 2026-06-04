"""SQLAlchemy models — KILN data model (Part III of the build plan).

Design anchors:
- **Build/Job split** (core insight #2): a Build is one physical run on one Printer; it
  carries one or more Jobs. Stages track at the Build; Job/Ticket status is DERIVED
  (see derivation.py). Material decrements once per Build (InventoryTxn) and allocates
  to Jobs.
- **FileVersion chain**: versions chain per Ticket; the Job pins the version that
  actually printed (R3, `Job.file_version_id`), distinct from `Ticket.current_file_version_id`.
- **Pragmatic audit** (not event-sourcing): `StageEvent` + `InventoryTxn` are append-only
  truth-of-record; the mutable convenience columns (`Build.current_stage/status`,
  `Job.queue_state/terminal_status`, `Material.qty_remaining`) are written in the SAME
  transaction as their event and are reconcilable via audit.py (column == fold(events)).

Append-only is a POLICY: nothing in the codebase updates or deletes StageEvent /
InventoryTxn rows. We do not claim full event-sourcing — the mutable columns are read
convenience, and a reconcile assertion guards them. That is deliberately simpler.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (
    BuildStatus,
    DryingState,
    InventoryReason,
    JobTerminalStatus,
    MaterialKind,
    NotificationKind,
    Priority,
    PrinterStatus,
    ProcessType,
    QCOutcome,
    QueueState,
    UserRole,
)

# Predictable constraint names make migrations + autogenerate stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(py_enum, name):
    # native PG enum type with a stable name
    return sa.Enum(py_enum, name=name, native_enum=True)


# --------------------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(sa.String(128))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"))
    # Auth lands in a later phase; the column exists, the verification logic does not yet.
    password_hash: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)


# --------------------------------------------------------------------------------------
# Machines & materials
# --------------------------------------------------------------------------------------
class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[MaterialKind] = mapped_column(_enum(MaterialKind, "material_kind"))
    spec: Mapped[str] = mapped_column(sa.String(128))            # e.g. "PETG", "PA12-CF", "Clear V4"
    color: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    unit: Mapped[str] = mapped_column(sa.String(8))             # "g" | "mL" | "L"

    # Fast-read; reconcilable as sum(InventoryTxn.delta). See audit.py.
    qty_remaining: Mapped[float] = mapped_column(sa.Float, default=0.0)
    # R6: nullable. Unset => no low-stock warning is ever raised for this material.
    reorder_threshold: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    lot: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    opened_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    shelf_life_days: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    drying_state: Mapped[DryingState | None] = mapped_column(
        _enum(DryingState, "drying_state"), nullable=True
    )

    # Powder virgin/used split (refresh-ratio display). Annotation only in v1: the core
    # reconcile invariant is on qty_remaining; full per-stream txn accounting is a Phase 4
    # inventory refinement (documented in docs/data-model.md).
    virgin_qty: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    used_qty: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

    txns: Mapped[list[InventoryTxn]] = relationship(back_populates="material")


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    process: Mapped[ProcessType] = mapped_column(_enum(ProcessType, "process_type"))
    status: Mapped[PrinterStatus] = mapped_column(
        _enum(PrinterStatus, "printer_status"), default=PrinterStatus.idle
    )

    build_volume_x: Mapped[float] = mapped_column(sa.Float)  # mm
    build_volume_y: Mapped[float] = mapped_column(sa.Float)
    build_volume_z: Mapped[float] = mapped_column(sa.Float)

    loaded_material_id: Mapped[int | None] = mapped_column(
        ForeignKey("materials.id"), nullable=True
    )
    # Capability/constraint bag the scheduler reads (e.g. {"enclosed": true,
    # "direct_drive": false, "materials": ["PA12-CF"]}). Data, not code branches.
    capabilities: Mapped[dict] = mapped_column(sa.JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

    loaded_material: Mapped[Material | None] = relationship()


# --------------------------------------------------------------------------------------
# Requests & files
# --------------------------------------------------------------------------------------
class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(sa.String(200))
    target_process: Mapped[ProcessType] = mapped_column(_enum(ProcessType, "process_type"))
    material_pref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    priority: Mapped[Priority] = mapped_column(_enum(Priority, "priority"), default=Priority.normal)
    deadline: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    current_file_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_versions.id", use_alter=True, name="fk_tickets_current_file_version"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

    requester: Mapped[User] = relationship()
    # Ticket -> Job is ONE-TO-MANY (R4: multi-part future-safe; v1 seeds one per ticket).
    jobs: Mapped[list[Job]] = relationship(
        back_populates="ticket", order_by="Job.created_at"
    )
    file_versions: Mapped[list[FileVersion]] = relationship(
        back_populates="ticket",
        order_by="FileVersion.version_no",
        foreign_keys="FileVersion.ticket_id",
    )
    current_file_version: Mapped[FileVersion | None] = relationship(
        foreign_keys=[current_file_version_id], post_update=True
    )


class FileVersion(Base):
    __tablename__ = "file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    version_no: Mapped[int] = mapped_column(sa.Integer)  # chained per ticket, 1..N

    filename: Mapped[str] = mapped_column(sa.String(255))
    blob_key: Mapped[str] = mapped_column(sa.String(512))   # local volume now; S3 seam later
    checksum: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)

    # Slicer-parsed estimates — always labeled "slicer est." in the UI, never measured.
    slicer_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    est_time_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    est_material_qty: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    est_material_unit: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)

    # Part bounding box (mm) — drives build-volume fit in the scheduler.
    bbox_x: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    bbox_z: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

    ticket: Mapped[Ticket] = relationship(
        back_populates="file_versions", foreign_keys=[ticket_id]
    )

    __table_args__ = (
        sa.UniqueConstraint("ticket_id", "version_no", name="ticket_version_unique"),
    )


# --------------------------------------------------------------------------------------
# The physical run + its parts
# --------------------------------------------------------------------------------------
class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int] = mapped_column(ForeignKey("printers.id"))
    process: Mapped[ProcessType] = mapped_column(_enum(ProcessType, "process_type"))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"), nullable=True)

    # Mutable fast-reads, reconcilable from build-level StageEvents (audit.fold_build).
    # current_stage = recipe position; status = side-state overlay.
    current_stage: Mapped[str] = mapped_column(sa.String(32))
    status: Mapped[BuildStatus] = mapped_column(
        _enum(BuildStatus, "build_status"), default=BuildStatus.running
    )

    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    printer: Mapped[Printer] = relationship()
    material: Mapped[Material | None] = relationship()
    jobs: Mapped[list[Job]] = relationship(back_populates="build")
    stage_events: Mapped[list[StageEvent]] = relationship(
        back_populates="build", order_by="StageEvent.at, StageEvent.id"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    # R3: the version that actually printed (may differ from the ticket's current version).
    file_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("file_versions.id"), nullable=True
    )
    # Null until scheduled onto a Build (G1 clause 3 territory).
    build_id: Mapped[int | None] = mapped_column(ForeignKey("builds.id"), nullable=True)

    # G1 clause 3: pre-Build spine. G1 clause 1: terminal override (nullable).
    queue_state: Mapped[QueueState] = mapped_column(
        _enum(QueueState, "queue_state"), default=QueueState.submitted
    )
    terminal_status: Mapped[JobTerminalStatus | None] = mapped_column(
        _enum(JobTerminalStatus, "job_terminal_status"), nullable=True
    )
    fail_reason: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)  # structured requeue reason
    qc_outcome: Mapped[QCOutcome | None] = mapped_column(
        _enum(QCOutcome, "qc_outcome"), nullable=True
    )

    # Per-part material allocation (filled when the Build is Done; informational).
    allocated_qty: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    allocated_unit: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)
    # R5: queue-entry timestamp. Age-boost is DERIVED from this, never stored.
    queued_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="jobs")
    build: Mapped[Build | None] = relationship(back_populates="jobs")
    file_version: Mapped[FileVersion | None] = relationship()
    events: Mapped[list[StageEvent]] = relationship(
        back_populates="job", order_by="StageEvent.at, StageEvent.id"
    )


# --------------------------------------------------------------------------------------
# Append-only truth-of-record
# --------------------------------------------------------------------------------------
class StageEvent(Base):
    """Append-only stage/lifecycle transition.

    Three flavours, distinguished by which FKs are set + the to_stage vocabulary:
      - build-level   : build_id set, job_id NULL   (recipe stage or side-state)
      - job pre-Build : job_id set,  build_id NULL  (submitted/queued/scheduled)
      - job override  : job_id set,  build_id set   (failed/qc_rejected/cancelled)
    """
    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    build_id: Mapped[int | None] = mapped_column(ForeignKey("builds.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)

    from_stage: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    to_stage: Mapped[str] = mapped_column(sa.String(32))

    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, index=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    build: Mapped[Build | None] = relationship(back_populates="stage_events")
    job: Mapped[Job | None] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()

    __table_args__ = (
        sa.CheckConstraint(
            "build_id IS NOT NULL OR job_id IS NOT NULL",
            name="event_targets_something",
        ),
    )


class InventoryTxn(Base):
    """Append-only material transaction. qty_remaining == sum(delta) over a material."""
    __tablename__ = "inventory_txns"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    build_id: Mapped[int | None] = mapped_column(ForeignKey("builds.id"), nullable=True)
    delta: Mapped[float] = mapped_column(sa.Float)  # negative = consume, positive = restock/adjust
    reason: Mapped[InventoryReason] = mapped_column(_enum(InventoryReason, "inventory_reason"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, index=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    material: Mapped[Material] = relationship(back_populates="txns")
    build: Mapped[Build | None] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    kind: Mapped[NotificationKind] = mapped_column(_enum(NotificationKind, "notification_kind"))
    message: Mapped[str] = mapped_column(sa.String(500))
    read: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship()
    ticket: Mapped[Ticket | None] = relationship()
    job: Mapped[Job | None] = relationship()
