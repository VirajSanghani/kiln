"""Domain enums + small ordering helpers shared across the model and derivation layers.

Enum *names* equal their *values* throughout, so SQLAlchemy's default (store the name)
and any string comparison agree.
"""
import enum


class UserRole(str, enum.Enum):
    operator = "operator"
    requester = "requester"


class ProcessType(str, enum.Enum):
    FDM = "FDM"
    SLA = "SLA"
    SLS = "SLS"
    MJF = "MJF"


class PrinterStatus(str, enum.Enum):
    idle = "idle"
    printing = "printing"
    down = "down"
    maintenance = "maintenance"


class MaterialKind(str, enum.Enum):
    filament = "filament"
    resin = "resin"
    powder = "powder"
    agent = "agent"


class DryingState(str, enum.Enum):
    dry = "dry"
    needs_drying = "needs_drying"
    drying = "drying"


class Priority(str, enum.Enum):
    critical = "critical"
    high = "high"
    normal = "normal"
    low = "low"


# Pre-Build lifecycle spine (lives OUTSIDE the recipe — R1).
class QueueState(str, enum.Enum):
    submitted = "submitted"
    queued = "queued"
    scheduled = "scheduled"


# Per-Job terminal override (G1 clause 1). Nullable on the Job.
class JobTerminalStatus(str, enum.Enum):
    failed = "failed"
    qc_rejected = "qc_rejected"
    cancelled = "cancelled"


class QCOutcome(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"


# Build side-state overlay. current_stage holds the recipe position; status holds this.
class BuildStatus(str, enum.Enum):
    running = "running"
    on_hold = "on_hold"
    failed = "failed"
    cancelled = "cancelled"
    completed = "completed"


class InventoryReason(str, enum.Enum):
    restock = "restock"
    consume = "consume"
    adjust = "adjust"


class NotificationKind(str, enum.Enum):
    started = "started"
    failed = "failed"
    ready_for_pickup = "ready_for_pickup"
    on_hold = "on_hold"


# Lower number = higher priority. Used by the scheduler (Phase 3); defined here so the
# ordering is single-sourced.
PRIORITY_RANK: dict[Priority, int] = {
    Priority.critical: 0,
    Priority.high: 1,
    Priority.normal: 2,
    Priority.low: 3,
}
