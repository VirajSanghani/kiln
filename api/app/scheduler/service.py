"""Scheduler service — assemble the full view, and the operator-only confirm action.

`build_schedule` is READ-ONLY: it never writes and never starts anything. `confirm_proposal`
is the ONLY mutating entry point and is called exclusively when a human clicks
"Confirm & start" — honouring "the scheduler proposes; a human disposes; nothing
auto-starts a physical machine."
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .. import recipes
from .. import stage_engine as engine
from ..audit import recompute_job_columns
from ..enums import BuildStatus, PrinterStatus, QueueState
from ..models import Build, Material, Printer, Job, StageEvent
from . import policy
from .assembly import propose_for_printer
from .capability import capability_match, eligible_jobs
from .config import Bucket, BuildProposal, RankedJob, SchedulerConfig, SchedulerView


def _queued_jobs(session) -> list[Job]:
    """§2 — the set of Queued Jobs: queue_state == queued, on no Build, not terminal."""
    return list(
        session.scalars(
            select(Job).where(
                Job.queue_state == QueueState.queued,
                Job.build_id.is_(None),
                Job.terminal_status.is_(None),
            )
        ).all()
    )


def _running_build(session, printer) -> Build | None:
    return session.scalars(
        select(Build).where(Build.printer_id == printer.id, Build.status == BuildStatus.running)
    ).first()


def _ranked(job, printer, config: SchedulerConfig) -> RankedJob:
    eff, boosted = policy.effective_priority(job, config)
    from ..enums import PRIORITY_RANK
    rank_to_prio = {r: p for p, r in PRIORITY_RANK.items()}
    return RankedJob(
        job_id=job.id, ticket_id=job.ticket_id, title=job.ticket.title,
        priority=job.ticket.priority.value, effective_priority=rank_to_prio[eff].value,
        boosted=boosted,
        deadline=job.ticket.deadline.isoformat() if job.ticket.deadline else None,
        age_hours=round(policy.age_hours(job, config), 2),
        needs_swap=capability_match(job, printer, config).needs_swap,
        reason=policy.reason(job, config),
    )


def build_schedule(session, config: SchedulerConfig | None = None) -> SchedulerView:
    config = config or SchedulerConfig()
    queued = _queued_jobs(session)
    printers = list(session.scalars(select(Printer).order_by(Printer.id)).all())

    buckets: list[Bucket] = []
    proposals: list[BuildProposal] = []

    for printer in printers:
        matched = eligible_jobs(queued, printer, config)
        ordered = policy.ordered(matched, config)

        running = _running_build(session, printer)
        # §5 no preemption + Phase-4 occupies_machine: a printer is unavailable for a new
        # Build if it is actively printing OR it holds a running Build in an on-machine
        # stage (SLS/MJF cooldown, SLA wash/cure — the part still ties up the printer).
        # Off-machine post-print stages (FDM support removal at a bench) leave it available.
        # Availability still keys on human-updated status — no telemetry.
        is_printing = printer.status == PrinterStatus.printing
        occupied = running is not None and recipes.occupies_machine(running.process, running.current_stage)
        busy = printer.status != PrinterStatus.idle or occupied
        preemption_note = None
        if is_printing and running is not None:
            preemption_note = (
                f"Printing Build #{running.id} — not preemptable; a Critical arrival goes "
                f"front-of-next-up, it does not interrupt the running print"
            )
        elif occupied:
            preemption_note = (
                f"Build #{running.id} in '{running.current_stage}' occupies the machine — "
                f"unavailable for a new Build until it clears"
            )

        buckets.append(Bucket(
            printer_id=printer.id, printer_name=printer.name, process=printer.process.value,
            printer_status=printer.status.value, busy=busy,
            running_build_id=running.id if running else None,
            preemption_note=preemption_note,
            next_up=[_ranked(j, printer, config) for j in ordered],
        ))

        # Proposals only for AVAILABLE printers: idle AND not machine-occupied.
        if printer.status == PrinterStatus.idle and not occupied:
            prop = propose_for_printer(session, printer, ordered, config)
            if prop is not None:
                proposals.append(prop)

    # §7: de-prioritize low-material proposals (sort them later) — but NEVER exclude them.
    proposals.sort(key=lambda p: (p.material.low_material, p.material.shortfall, p.printer_id))

    return SchedulerView(
        buckets=buckets, proposals=proposals,
        age_boost_enabled=config.age_boost_enabled, age_boost_hours=config.age_boost_hours,
        fill_cap_pct=config.fill_pct_cap,
        batching={p.value: v for p, v in config.batching.items()},
    )


# ---------------------------------------------------------------- operator confirm
def _resolve_material(session, jobs) -> Material | None:
    spec = jobs[0].ticket.material_pref
    if spec is None:
        return None
    return session.scalars(select(Material).where(Material.spec == spec).order_by(Material.id)).first()


def confirm_proposal(session, printer: Printer, jobs: list[Job], *, actor=None, note=None) -> Build:
    """Materialize a proposed (or operator-edited) Build and START it. OPERATOR ACTION ONLY.

    `jobs` is the operator's chosen set (edit = pass a subset; dismiss = never call this).
    Creates the Build, pins each Job's FileVersion + moves it to scheduled-on-build, then
    engine.start records the entry event. Sets the printer to printing (human-updated
    status — no telemetry). Returns the started Build; reconcile stays green.
    """
    if not jobs:
        raise ValueError("cannot confirm an empty proposal")
    if printer.status != PrinterStatus.idle:
        raise ValueError(f"printer {printer.name} is {printer.status.value}, not idle — no preemption")

    material = _resolve_material(session, jobs)
    # current_stage is set authoritatively by engine.start below; seed it with the entry
    # stage up front so the NOT NULL column is satisfied on any intermediate flush.
    build = Build(printer=printer, process=printer.process, material=material,
                  current_stage=engine.entry_stage(printer.process))
    session.add(build)

    now = datetime.now(timezone.utc)
    for j in jobs:
        if j.terminal_status is not None or j.build_id is not None:
            raise ValueError(f"Job {j.id} is not an unassigned queued job")
        j.build = build
        if j.file_version is None:                      # R3: pin the version that prints
            j.file_version = j.ticket.current_file_version
        e = StageEvent(from_stage=j.queue_state.value, to_stage=QueueState.scheduled.value, at=now, job=j)
        e.actor = actor
        session.add(e)
        session.flush()
        recompute_job_columns(j)                        # queue_state -> scheduled (same txn)

    engine.start(session, build, actor=actor, note=note)
    printer.status = PrinterStatus.printing
    session.flush()
    return build
