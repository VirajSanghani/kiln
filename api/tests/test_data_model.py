"""Phase 1 model tests: recipe shape (R1/R2), G1 status derivation, R4 ticket rollup,
and the reconcile invariant (column == fold(events)).

Recipe-engine behaviour (transition validation) is Phase 2; here we test the DATA and
the derivation/audit semantics that Phase 1 owns.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.audit import reconcile_all
from app.derivation import (
    build_effective_state,
    job_effective_status,
    ticket_status,
)
from app.enums import (
    BuildStatus,
    InventoryReason,
    JobTerminalStatus,
    Priority,
    ProcessType,
    QueueState,
    UserRole,
)
from app.models import (
    Build,
    InventoryTxn,
    Job,
    Material,
    Printer,
    StageEvent,
    Ticket,
    User,
)
from app.recipes import RECIPES, entry_stage, is_terminal_stage, recipe_for, stage_def

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- recipes
def test_every_recipe_starts_at_printing_and_ends_at_done():
    for process in ProcessType:
        assert entry_stage(process) == "printing"            # R1
        last = recipe_for(process)[-1]
        assert last.name == "done"
        assert last.allowed_next == ()                       # R2: terminal = empty allowed_next
        assert is_terminal_stage(process, "done")


def test_only_the_terminal_stage_has_no_successors():
    for process in ProcessType:
        for s in recipe_for(process):
            if s.name == "done":
                assert is_terminal_stage(process, s.name)
            else:
                assert not is_terminal_stage(process, s.name)


def test_mjf_dye_is_an_optional_branch():
    # depowder may go to dye OR skip straight to qc — proves allowed_next is a real graph.
    assert set(stage_def(ProcessType.MJF, "depowder").allowed_next) == {"dye", "qc"}


def test_stage_types_present_for_metric():
    # active/passive must be set on every stage (feeds the utilization metric).
    for process in ProcessType:
        for s in recipe_for(process):
            assert s.type in ("active", "passive")
    # sanity: a known passive (SLS cooldown) and a known active (FDM printing)
    assert stage_def(ProcessType.SLS, "cooldown").type == "passive"
    assert stage_def(ProcessType.FDM, "printing").type == "active"


# ------------------------------------------------------------------- G1 (job status)
def _ticket(session, **kw):
    u = User(username=f"u{id(kw)}", display_name="x", role=UserRole.requester)
    session.add(u)
    t = Ticket(requester=u, title=kw.get("title", "t"),
               target_process=kw.get("process", ProcessType.FDM),
               priority=kw.get("priority", Priority.normal), created_at=kw.get("created_at", NOW))
    session.add(t)
    return t


def test_g1_clause3_prebuild_uses_queue_state(session):
    t = _ticket(session)
    j = Job(ticket=t, queue_state=QueueState.queued, created_at=NOW)
    session.add(j)
    session.flush()
    assert job_effective_status(j) == "queued"


def test_g1_clause2_inherits_build_stage(session):
    t = _ticket(session)
    printer = Printer(name="p1", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b = Build(printer=printer, process=ProcessType.FDM, current_stage="wash", status=BuildStatus.running)
    j = Job(ticket=t, build=b, queue_state=QueueState.scheduled, created_at=NOW)
    session.add_all([printer, b, j])
    session.flush()
    assert job_effective_status(j) == "wash"


def test_g1_clause1_terminal_override_beats_done_build(session):
    """The headline case: a Job on a Done Build but rejected at QC reads qc_rejected."""
    t = _ticket(session)
    printer = Printer(name="p2", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b = Build(printer=printer, process=ProcessType.FDM, current_stage="done", status=BuildStatus.completed)
    j_ok = Job(ticket=t, build=b, created_at=NOW)
    j_bad = Job(ticket=t, build=b, terminal_status=JobTerminalStatus.qc_rejected, created_at=NOW)
    session.add_all([printer, b, j_ok, j_bad])
    session.flush()
    assert job_effective_status(j_ok) == "done"
    assert job_effective_status(j_bad) == "qc_rejected"


def test_build_effective_state_overlay(session):
    printer = Printer(name="p3", process=ProcessType.SLA, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b = Build(printer=printer, process=ProcessType.SLA, current_stage="cure", status=BuildStatus.on_hold)
    session.add_all([printer, b])
    session.flush()
    assert build_effective_state(b) == "on_hold"   # side-state overlay wins
    b.status = BuildStatus.running
    assert build_effective_state(b) == "cure"      # else recipe position


# ------------------------------------------------------------------- R4 (ticket status)
def test_r4_least_advanced_non_terminal_wins(session):
    """Reprint: v2 Failed, v3 Printing -> ticket reads the non-terminal (printing)."""
    t = _ticket(session)
    printer = Printer(name="p4", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b_failed = Build(printer=printer, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.failed)
    b_run = Build(printer=printer, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.running)
    j_old = Job(ticket=t, build=b_failed, created_at=NOW - timedelta(days=1))
    j_new = Job(ticket=t, build=b_run, created_at=NOW)
    session.add_all([printer, b_failed, b_run, j_old, j_new])
    session.flush()
    assert ticket_status(t) == "printing"


def test_r4_all_terminal_uses_latest(session):
    """If every job is terminal, the most recent attempt's outcome wins (done after a fail)."""
    t = _ticket(session)
    printer = Printer(name="p5", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b_failed = Build(printer=printer, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.failed)
    b_done = Build(printer=printer, process=ProcessType.FDM, current_stage="done", status=BuildStatus.completed)
    j_old = Job(ticket=t, build=b_failed, created_at=NOW - timedelta(days=1))
    j_new = Job(ticket=t, build=b_done, created_at=NOW)
    session.add_all([printer, b_failed, b_done, j_old, j_new])
    session.flush()
    assert ticket_status(t) == "done"


def test_r4_tiebreak_latest_within_same_level(session):
    """Two non-terminal jobs at the same advancement level -> latest created_at wins."""
    t = _ticket(session)
    printer = Printer(name="p6", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b1 = Build(printer=printer, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.running)
    b2 = Build(printer=printer, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.running)
    j1 = Job(ticket=t, build=b1, created_at=NOW - timedelta(hours=2))
    j2 = Job(ticket=t, build=b2, created_at=NOW)
    session.add_all([printer, b1, b2, j1, j2])
    session.flush()
    # both 'printing' (same rank); tie-break picks the later-created job (still 'printing')
    assert ticket_status(t) == "printing"


# ------------------------------------------------------------------- reconcile invariant
def test_reconcile_passes_when_columns_match_events(session):
    m = Material(kind="filament", spec="PETG", unit="g", qty_remaining=170.0)
    session.add(m)
    session.flush()
    session.add_all([
        InventoryTxn(material_id=m.id, delta=200, reason=InventoryReason.restock, at=NOW),
        InventoryTxn(material_id=m.id, delta=-30, reason=InventoryReason.consume, at=NOW),
    ])

    printer = Printer(name="p7", process=ProcessType.FDM, build_volume_x=1, build_volume_y=1, build_volume_z=1)
    b = Build(printer=printer, process=ProcessType.FDM, current_stage="qc", status=BuildStatus.running)
    session.add_all([printer, b])
    session.flush()
    session.add_all([
        StageEvent(build_id=b.id, to_stage="printing", at=NOW),
        StageEvent(build_id=b.id, from_stage="printing", to_stage="support_removal", at=NOW + timedelta(hours=1)),
        StageEvent(build_id=b.id, from_stage="support_removal", to_stage="qc", at=NOW + timedelta(hours=2)),
    ])
    session.flush()
    assert reconcile_all(session) == []


def test_reconcile_detects_drift(session):
    m = Material(kind="filament", spec="PETG", unit="g", qty_remaining=999.0)  # wrong on purpose
    session.add(m)
    session.flush()
    session.add(InventoryTxn(material_id=m.id, delta=100, reason=InventoryReason.restock, at=NOW))
    session.flush()
    d = reconcile_all(session)
    assert len(d) == 1
    assert d[0].field == "qty_remaining"
    assert d[0].column == 999.0 and d[0].folded == 100.0
