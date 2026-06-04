"""Status DERIVATION — the single source of truth for "what state is this in?".

Job/Ticket status are never stored as a single field; they are computed here from the
mutable convenience columns. This keeps the rules in one auditable place.

G1 (Job effective status), verbatim:
    terminal override (Failed/QC-rejected/Cancelled)
      -> else inherited Build stage (if the Job is on a Build)
        -> else its own pre-Build queue state.

R4 (Ticket status): Ticket->Job is one-to-many. Ticket status =
    the LEAST-ADVANCED non-terminal job's status,
    tie-broken by LATEST created_at within the same advancement level;
    if every job is terminal, the latest-by-created_at job's status (so a re-print whose
    newest attempt is Done reads Done; one whose newest attempt Failed reads Failed).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .enums import BuildStatus, ProcessType

if TYPE_CHECKING:  # avoid import cycle at runtime
    from .models import Build, Job, Ticket

# Statuses that mean "this job's lifecycle is over" for ticket-rollup purposes.
TICKET_TERMINAL = {"failed", "qc_rejected", "cancelled", "done"}


def build_effective_state(build: "Build") -> str:
    """A Build's externally-visible state: side-state overlay wins, else recipe position."""
    if build.status == BuildStatus.failed:
        return "failed"
    if build.status == BuildStatus.cancelled:
        return "cancelled"
    if build.status == BuildStatus.on_hold:
        return "on_hold"
    # running or completed -> the recipe position (which is "done" when completed)
    return build.current_stage


def job_effective_status(job: "Job") -> str:
    """G1, three clauses, in order."""
    if job.terminal_status is not None:                       # 1. terminal override
        return job.terminal_status.value
    if job.build_id is not None and job.build is not None:    # 2. inherited Build stage
        return build_effective_state(job.build)
    return job.queue_state.value                             # 3. pre-Build queue state


def coarse_rank(status: str, process: ProcessType) -> int:
    """Coarse lifecycle 'advancement level' for R4.

    Deliberately coarse (not per-stage) — ticket rollup only needs ordering across the
    spine, and a per-process fine rank would buy nothing here. printing < mid-build < done.
    """
    pre = {"submitted": 0, "queued": 1, "scheduled": 2}
    if status in pre:
        return pre[status]
    if status == "printing":
        return 3
    if status == "done":
        return 5
    # on_hold or any post-printing-pre-done recipe stage (support_removal, wash, qc, ...)
    return 4


def ticket_status(ticket: "Ticket") -> str:
    """R4 rollup. See module docstring."""
    jobs: list["Job"] = list(ticket.jobs)
    if not jobs:
        return "submitted"

    enriched = [(job_effective_status(j), j) for j in jobs]
    non_terminal = [(s, j) for (s, j) in enriched if s not in TICKET_TERMINAL]

    if non_terminal:
        # least-advanced first; within a level, latest created_at first
        non_terminal.sort(
            key=lambda t: (coarse_rank(t[0], ticket.target_process), -t[1].created_at.timestamp())
        )
        return non_terminal[0][0]

    # all jobs terminal -> the most recent attempt's outcome
    enriched.sort(key=lambda t: t[1].created_at, reverse=True)
    return enriched[0][0]
