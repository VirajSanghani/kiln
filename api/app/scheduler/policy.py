"""Ordering policy — §4 + §4.1. EXPLICIT and DEFENSIBLE, not an optimizer.

Within a capability bucket, Jobs are ordered by the documented lexicographic key:
    1. priority   (critical > high > normal > low) — with the age-boost applied
    2. deadline   (dated before undated; earlier first)
    3. age        (older queued first — fairness, anti-starvation)
    4. job id     (stable, deterministic tie-break)

An operator can always answer "why is this job next?" — that legibility is the point.
"""
from __future__ import annotations

from datetime import datetime

from ..enums import PRIORITY_RANK, Priority
from .config import SchedulerConfig

_RANK_TO_PRIORITY = {rank: prio for prio, rank in PRIORITY_RANK.items()}


def _entered_queue_at(job) -> datetime | None:
    return job.queued_at or job.created_at


def age_hours(job, config: SchedulerConfig) -> float:
    qa = _entered_queue_at(job)
    if qa is None:
        return 0.0
    return max(0.0, (config.now - qa).total_seconds() / 3600.0)


def effective_priority(job, config: SchedulerConfig) -> tuple[int, bool]:
    """Return (effective rank, boosted?). Age-boost lifts priority exactly ONE tier
    after the wait threshold (§4.1) — derived from queued_at, never stored."""
    base = PRIORITY_RANK[job.ticket.priority]
    if config.age_boost_enabled and base > 0 and age_hours(job, config) >= config.age_boost_hours:
        return base - 1, True
    return base, False


def _deadline_key(job) -> tuple[int, int]:
    # dated (0) sorts before undated (1); earlier date first.
    d = job.ticket.deadline
    return (0, d.toordinal()) if d is not None else (1, 0)


def order_key(job, config: SchedulerConfig) -> tuple:
    eff, _ = effective_priority(job, config)
    qa = _entered_queue_at(job)
    age_ts = qa.timestamp() if qa is not None else float("inf")  # older (smaller) first
    return (eff, _deadline_key(job), age_ts, job.id)


def ordered(jobs, config: SchedulerConfig) -> list:
    """Deterministic ordering — the id tie-break guarantees same inputs → same order."""
    return sorted(jobs, key=lambda j: order_key(j, config))


def _humanize_age(hours: float) -> str:
    if hours >= 48:
        return f"{int(hours // 24)}d"
    if hours >= 1:
        return f"{int(hours)}h"
    return "<1h"


def reason(job, config: SchedulerConfig) -> str:
    """The §8 'why is this job next?' string."""
    eff, boosted = effective_priority(job, config)
    base = job.ticket.priority.value
    if boosted:
        lifted = _RANK_TO_PRIORITY[eff].value
        bits = [f"{base}→{lifted} (age-boosted, waited {_humanize_age(age_hours(job, config))})"]
    else:
        bits = [base.capitalize()]
    if job.ticket.deadline is not None:
        bits.append(f"due {job.ticket.deadline.isoformat()}")
    else:
        bits.append(f"queued {_humanize_age(age_hours(job, config))}")
    return "; ".join(bits)
