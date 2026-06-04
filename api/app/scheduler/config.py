"""Scheduler configuration, capability data tables, and the view dataclasses.

The dataclasses are the scheduler's output contract — plain, serializable, and consumed
by the operator console (Phase 5). Nothing here imports the rest of the scheduler, so
there are no cycles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..enums import ProcessType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# §6: batching default — OFF for FDM/SLA (fair, simple); ON for SLS/MJF (fill the bed).
DEFAULT_BATCHING: dict[ProcessType, bool] = {
    ProcessType.FDM: False,
    ProcessType.SLA: False,
    ProcessType.SLS: True,
    ProcessType.MJF: True,
}

# §3: a material spec may REQUIRE certain printer capabilities. Data, not code — extend by
# adding rows. Matched against Printer.capabilities (a JSON bag like {"enclosed": true}).
MATERIAL_REQUIREMENTS: dict[str, dict] = {
    "PA12-CF": {"enclosed": True},     # carbon-filled nylon needs an enclosure
    "TPU": {"direct_drive": True},     # flexible filament needs a direct-drive extruder
}


@dataclass
class SchedulerConfig:
    # `now` is injected so age-boost and ordering are deterministic and testable.
    now: datetime = field(default_factory=_utcnow)
    age_boost_enabled: bool = True            # §4.1 toggleable
    age_boost_hours: float = 72.0             # §4.1 configurable threshold (e.g. 3 days)
    fill_pct_cap: float = 0.80                # §6.1 footprint fill cap for batching
    allow_swaps: bool = True                  # §3 "swap acceptable" — eligible despite loaded mismatch
    batching: dict[ProcessType, bool] = field(default_factory=lambda: dict(DEFAULT_BATCHING))


# ----------------------------------------------------------------- output contract
@dataclass
class RankedJob:
    job_id: int
    ticket_id: int
    title: str
    priority: str
    effective_priority: str       # after age-boost
    boosted: bool                 # §4.1 surfaced as "boosted"
    deadline: str | None
    age_hours: float
    needs_swap: bool              # eligible only via a spool swap
    reason: str                   # §8 "why is this job next?"


@dataclass
class MaterialAnnotation:
    material_spec: str | None
    projected: float
    unit: str | None
    remaining: float | None
    fits: bool
    shortfall: float              # >0 means short by this much
    low_material: bool            # §7 de-prioritize (never exclude)
    note: str                     # "fits stock" / "short by 12g — flagged"


@dataclass
class Bucket:
    printer_id: int
    printer_name: str
    process: str
    printer_status: str
    busy: bool                    # §5 currently Printing → not preemptable
    running_build_id: int | None
    preemption_note: str | None
    next_up: list[RankedJob]


@dataclass
class BuildProposal:
    printer_id: int
    printer_name: str
    process: str
    material_spec: str | None
    job_ids: list[int]
    parts: int
    fill_pct: float               # footprint fill of the plate
    fill_cap_pct: float
    needs_swap: bool
    material: MaterialAnnotation
    reason: str


@dataclass
class SchedulerView:
    buckets: list[Bucket]
    proposals: list[BuildProposal]
    # echo of the knobs, so the console can render the toggles + their tradeoff
    age_boost_enabled: bool
    age_boost_hours: float
    fill_cap_pct: float
    batching: dict[str, bool]
