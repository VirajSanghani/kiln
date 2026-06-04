"""Phase 2 gate — the recipe engine.

Covers: each process walks printing->done; invalid transitions are rejected; failure/
hold/cancel from multiple stages; lossless hold/resume; multi-Job advancement with one
overridden Job; reconcile passes after every sequence; and recipe-as-data (a synthetic
process drives the engine with zero engine edits).
"""
import pytest

from app import stage_engine as eng
from app.audit import reconcile_all
from app.derivation import job_effective_status
from app.enums import BuildStatus, Priority, ProcessType, UserRole
from app.models import Build, Job, Printer, Ticket, User
from app.recipes import RECIPES, StageDef, entry_stage, is_terminal_stage, recipe_for, stage_def


# --------------------------------------------------------------------------- helpers
def _canonical_path(process):
    """Follow the first allowed_next at each step to the terminal (data-driven walk)."""
    cur = entry_stage(process)
    path = [cur]
    while not is_terminal_stage(process, cur):
        cur = stage_def(process, cur).allowed_next[0]
        path.append(cur)
    return path


def _new_build(session, process, n_jobs=1):
    op = User(username=f"op{id(session)}{process.value}", display_name="op", role=UserRole.operator)
    req = User(username=f"rq{id(session)}{process.value}", display_name="rq", role=UserRole.requester)
    printer = Printer(name=f"{process.value}-{id(session) % 100000}", process=process,
                      build_volume_x=300, build_volume_y=300, build_volume_z=300)
    build = Build(printer=printer, process=process)  # current_stage set by engine.start
    session.add_all([op, req, printer, build])
    jobs = []
    for i in range(n_jobs):
        t = Ticket(requester=req, title=f"part {i}", target_process=process, priority=Priority.normal)
        j = Job(ticket=t, build=build)
        session.add_all([t, j])
        jobs.append(j)
    eng.start(session, build, actor=op)
    session.flush()
    return build, jobs, op


def _commit_ok(session):
    session.commit()
    assert reconcile_all(session) == [], "reconcile drift after sequence"


# ---------------------------------------------------------------- full recipe walks
@pytest.mark.parametrize("process", list(ProcessType))
def test_each_process_walks_printing_to_done(session, process):
    build, jobs, op = _new_build(session, process)
    assert build.current_stage == "printing"
    assert build.status == BuildStatus.running

    path = _canonical_path(process)
    for to in path[1:]:
        eng.advance(session, build, to, actor=op)
        assert build.current_stage == to

    assert build.current_stage == "done"
    assert build.status == BuildStatus.completed
    assert build.completed_at is not None
    assert job_effective_status(jobs[0]) == "done"
    _commit_ok(session)


def test_mjf_dye_skip_branch(session):
    """MJF depowder -> qc (skip the optional Dye) is a legal alternate edge."""
    build, jobs, op = _new_build(session, ProcessType.MJF)
    eng.advance(session, build, "cooldown", actor=op)
    eng.advance(session, build, "depowder", actor=op)
    eng.advance(session, build, "qc", actor=op)   # skips dye
    eng.advance(session, build, "done", actor=op)
    assert build.status == BuildStatus.completed
    _commit_ok(session)


# ----------------------------------------------------------------- invalid transitions
def test_invalid_transition_is_rejected_not_silent(session):
    build, _, op = _new_build(session, ProcessType.FDM)
    with pytest.raises(eng.TransitionError) as ei:
        eng.advance(session, build, "qc", actor=op)  # printing -> qc skips support_removal
    assert "printing -> qc" in str(ei.value)
    assert "support_removal" in str(ei.value)        # error names the allowed set
    # state unchanged by the rejected attempt
    assert build.current_stage == "printing"


def test_cannot_advance_completed_build(session):
    build, _, op = _new_build(session, ProcessType.FDM)
    for to in _canonical_path(ProcessType.FDM)[1:]:
        eng.advance(session, build, to, actor=op)
    with pytest.raises(eng.TransitionError):
        eng.advance(session, build, "done", actor=op)


def test_cannot_advance_while_on_hold(session):
    build, _, op = _new_build(session, ProcessType.SLA)
    eng.hold(session, build, actor=op)
    with pytest.raises(eng.TransitionError):
        eng.advance(session, build, "drain", actor=op)


# ------------------------------------------------------------ side-transitions / hold
def test_hold_resume_is_lossless_midway(session):
    build, jobs, op = _new_build(session, ProcessType.SLA)
    eng.advance(session, build, "drain", actor=op)
    eng.advance(session, build, "wash", actor=op)

    eng.hold(session, build, actor=op, note="out of IPA")
    assert build.status == BuildStatus.on_hold
    assert build.current_stage == "wash"             # parked, not lost
    assert job_effective_status(jobs[0]) == "on_hold"

    eng.resume(session, build, actor=op)
    assert build.status == BuildStatus.running
    assert build.current_stage == "wash"             # restored

    eng.advance(session, build, "cure", actor=op)
    eng.advance(session, build, "qc", actor=op)
    eng.advance(session, build, "done", actor=op)
    assert build.status == BuildStatus.completed
    _commit_ok(session)


def test_fail_from_running_and_from_hold(session):
    b1, _, op = _new_build(session, ProcessType.FDM)
    eng.advance(session, b1, "support_removal", actor=op)
    eng.fail(session, b1, actor=op, reason="layer shift")
    assert b1.status == BuildStatus.failed
    assert b1.current_stage == "support_removal"     # parked at point of failure

    b2, _, _ = _new_build(session, ProcessType.SLS)
    eng.hold(session, b2, actor=op)
    eng.fail(session, b2, actor=op, reason="machine down")
    assert b2.status == BuildStatus.failed
    _commit_ok(session)


def test_cancel_from_midstage(session):
    build, jobs, op = _new_build(session, ProcessType.SLS)
    eng.advance(session, build, "cooldown", actor=op)
    eng.cancel(session, build, actor=op, note="job pulled")
    assert build.status == BuildStatus.cancelled
    assert job_effective_status(jobs[0]) == "cancelled"
    _commit_ok(session)


# ------------------------------------------------- multi-Job advancement + override
def test_multijob_build_one_override_others_advance(session):
    build, jobs, op = _new_build(session, ProcessType.FDM, n_jobs=3)
    j_ok1, j_ok2, j_bad = jobs

    eng.advance(session, build, "support_removal", actor=op)
    # one part fails QC inspection — a per-Job override, mid-build
    eng.reject_job(session, j_bad, actor=op, note="warped")
    assert job_effective_status(j_bad) == "qc_rejected"

    # the Build carries on for the others
    eng.advance(session, build, "qc", actor=op)
    eng.advance(session, build, "done", actor=op)

    assert build.status == BuildStatus.completed
    assert job_effective_status(j_ok1) == "done"
    assert job_effective_status(j_ok2) == "done"
    assert job_effective_status(j_bad) == "qc_rejected"   # stayed put (G1 clause 1)
    _commit_ok(session)


def test_double_override_rejected(session):
    build, jobs, op = _new_build(session, ProcessType.FDM)
    eng.fail_job(session, jobs[0], actor=op, reason="x")
    with pytest.raises(eng.TransitionError):
        eng.reject_job(session, jobs[0], actor=op)


# ----------------------------------------------------------- recipe-as-data proof
def test_adding_a_process_needs_no_engine_edits(session):
    """Register a brand-new recipe and drive the ENGINE'S validation against it.

    The engine never branches on process identity, so a never-before-seen process is
    validated purely from its data. (A real new process also needs an enum value + a
    one-line enum migration — schema/data, not engine code.)
    """
    SENTINEL = "DLP_TEST"
    RECIPES[SENTINEL] = (
        StageDef("printing", "Printing", "active", ("settle",)),
        StageDef("settle", "Settle", "passive", ("cure",)),
        StageDef("cure", "Cure", "active", ("done",)),
        StageDef("done", "Done", "passive", ()),
    )
    try:
        # legal edges pass, illegal edges raise — with no engine change
        eng.assert_advance_allowed(SENTINEL, "printing", "settle")
        eng.assert_advance_allowed(SENTINEL, "settle", "cure")
        eng.assert_advance_allowed(SENTINEL, "cure", "done")
        with pytest.raises(eng.TransitionError):
            eng.assert_advance_allowed(SENTINEL, "printing", "cure")
        assert is_terminal_stage(SENTINEL, "done")
        assert _canonical_path(SENTINEL) == ["printing", "settle", "cure", "done"]
    finally:
        del RECIPES[SENTINEL]
