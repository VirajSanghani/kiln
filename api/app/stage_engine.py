"""The recipe engine — Build-level stage transitions + universal side-transitions.

ONE engine, driven entirely by the recipe DATA (`app/recipes`). It contains NO
per-process branches: every decision reads `recipe_for(build.process)` / `allowed_next` /
`is_terminal_stage`. Adding a process = adding a recipe entry (+ an enum value + a tiny
enum migration); this file is never touched. `assert_advance_allowed` is pure (registry
only) and is what the recipe-as-data test drives against a synthetic process.

Invariants honoured:
- Invalid transitions raise `TransitionError` with the allowed set — never a silent no-op.
- Two-axis model: a side-state sets `status` and PARKS `current_stage`; resume restores it.
- Every op writes a StageEvent AND recomputes the mutable column via the Phase-1 audit
  folds, in the caller's transaction (we flush; the caller commits) — so a single commit
  persists event + column atomically and `reconcile_all` stays green.
- Multi-Job advancement is FREE: Job status is derived from the Build (G1 clause 2), so
  advancing the Build advances every non-overridden Job; a Job with a terminal override
  (G1 clause 1) stays put and never blocks its plate-mates.

Material decrement on Done is intentionally NOT here — that is Phase 4 (inventory). The
`on_done` hook below marks the seam without implementing it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .audit import recompute_build_columns, recompute_job_columns
from .enums import BuildStatus, JobTerminalStatus, QCOutcome
from .recipes import entry_stage, is_terminal_stage, stage_def
from .models import StageEvent

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .models import Build, Job, User

ON_HOLD = "on_hold"
FAILED = "failed"
CANCELLED = "cancelled"

# A Build in one of these is done with the recipe; nothing may advance it.
TERMINAL_BUILD_STATUSES = {
    BuildStatus.failed,
    BuildStatus.cancelled,
    BuildStatus.completed,
}


class TransitionError(ValueError):
    """Raised on any illegal transition. Carries a human-readable reason."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(session, build, *, frm, to, actor, note, job=None) -> StageEvent:
    e = StageEvent(from_stage=frm, to_stage=to, at=_now(), note=note)
    e.build = build
    e.job = job
    e.actor = actor
    session.add(e)
    return e


# ---------------------------------------------------------------- pure validation core
def assert_advance_allowed(process, current_stage: str, to_stage: str) -> None:
    """Pure: raise unless `current_stage -> to_stage` is a legal recipe edge.

    No DB, no per-process code — just the registry. This is the proof surface for
    recipe-as-data: a brand-new recipe validates here with zero engine changes.
    """
    allowed = stage_def(process, current_stage).allowed_next
    if to_stage not in allowed:
        raise TransitionError(
            f"invalid transition ({getattr(process, 'value', process)}): "
            f"{current_stage} -> {to_stage}. "
            f"Allowed from {current_stage}: {list(allowed) or '(terminal — no successors)'}"
        )


# ------------------------------------------------------------------ Build transitions
def start(session: "Session", build: "Build", *, actor: "User | None" = None, note=None):
    """Enter the recipe at its entry stage (printing) and record the entry event."""
    if any(e.job_id is None for e in build.stage_events):
        raise TransitionError(f"Build {build.id} has already started")
    entry = entry_stage(build.process)
    build.current_stage = entry
    build.status = BuildStatus.running
    build.started_at = _now()
    _event(session, build, frm=None, to=entry, actor=actor, note=note)
    session.flush()
    recompute_build_columns(build)
    return build


def advance(session: "Session", build: "Build", to_stage: str, *, actor=None, note=None):
    """Advance the Build one legal step. Advances all non-overridden Jobs by derivation."""
    if build.status == BuildStatus.on_hold:
        raise TransitionError(
            f"Build {build.id} is on hold; resume() before advancing"
        )
    if build.status in TERMINAL_BUILD_STATUSES:
        raise TransitionError(
            f"Build {build.id} is {build.status.value}; cannot advance"
        )
    assert_advance_allowed(build.process, build.current_stage, to_stage)
    _event(session, build, frm=build.current_stage, to=to_stage, actor=actor, note=note)
    if is_terminal_stage(build.process, to_stage):
        build.completed_at = _now()
    session.flush()
    recompute_build_columns(build)
    if build.status == BuildStatus.completed:
        on_done(session, build)
    return build


def hold(session: "Session", build: "Build", *, actor=None, note=None):
    if build.status != BuildStatus.running:
        raise TransitionError(
            f"can only hold a running Build; Build {build.id} is {build.status.value}"
        )
    # current_stage is left PARKED; only the status overlay changes.
    _event(session, build, frm=build.current_stage, to=ON_HOLD, actor=actor, note=note)
    session.flush()
    recompute_build_columns(build)
    return build


def resume(session: "Session", build: "Build", *, actor=None, note=None):
    if build.status != BuildStatus.on_hold:
        raise TransitionError(
            f"can only resume a Build on hold; Build {build.id} is {build.status.value}"
        )
    parked = build.current_stage  # restored losslessly
    _event(session, build, frm=ON_HOLD, to=parked, actor=actor, note=note)
    session.flush()
    recompute_build_columns(build)
    return build


def fail(session: "Session", build: "Build", *, actor=None, reason=None):
    """Whole-Build failure — allowed from running OR on hold."""
    if build.status in TERMINAL_BUILD_STATUSES:
        raise TransitionError(f"Build {build.id} is already {build.status.value}")
    _event(session, build, frm=build.current_stage, to=FAILED, actor=actor, note=reason)
    session.flush()
    recompute_build_columns(build)
    return build


def cancel(session: "Session", build: "Build", *, actor=None, note=None):
    if build.status in TERMINAL_BUILD_STATUSES:
        raise TransitionError(f"Build {build.id} is already {build.status.value}")
    _event(session, build, frm=build.current_stage, to=CANCELLED, actor=actor, note=note)
    session.flush()
    recompute_build_columns(build)
    return build


# ------------------------------------------------------------ per-Job overrides (G1 #1)
def _job_override(session, job, status: JobTerminalStatus, *, actor, note, qc=None):
    if job.terminal_status is not None:
        raise TransitionError(
            f"Job {job.id} is already terminal ({job.terminal_status.value})"
        )
    frm = job.build.current_stage if job.build is not None else job.queue_state.value
    e = StageEvent(from_stage=frm, to_stage=status.value, at=_now(), note=note)
    e.job = job
    e.build = job.build  # build context (may be None for a pre-Build cancel)
    e.actor = actor
    session.add(e)
    if qc is not None:
        job.qc_outcome = qc
    if status == JobTerminalStatus.failed and note:
        job.fail_reason = note
    session.flush()
    recompute_job_columns(job)
    return job


def reject_job(session: "Session", job: "Job", *, actor=None, note=None):
    """One part fails QC. Does NOT touch the Build — its plate-mates carry on."""
    return _job_override(session, job, JobTerminalStatus.qc_rejected,
                         actor=actor, note=note, qc=QCOutcome.failed)


def fail_job(session: "Session", job: "Job", *, actor=None, reason=None):
    return _job_override(session, job, JobTerminalStatus.failed, actor=actor, note=reason)


def cancel_job(session: "Session", job: "Job", *, actor=None, note=None):
    return _job_override(session, job, JobTerminalStatus.cancelled, actor=actor, note=note)


# --------------------------------------------------------------------------- seam hook
def on_done(session: "Session", build: "Build") -> None:
    """Hook fired when a Build reaches Done.

    Phase 4 wires material decrement + per-Job allocation + ready-for-pickup
    notifications here. Phase 2 leaves it a documented no-op so the engine stays
    scope-fenced to stage logic.
    """
    return None
