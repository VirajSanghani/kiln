"""Phase 3 gate — the scheduler, built to SCHEDULER_DESIGN.md §9.

Six checks: capability partition; ordering + age-boost; no-preemption; build assembly
(group / don't / fill-cap); material annotation (flag-but-proposable); determinism.
Plus capability swap handling and the operator confirm action.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.audit import reconcile_all
from app.enums import (
    BuildStatus,
    MaterialKind,
    PrinterStatus,
    Priority,
    ProcessType,
    QueueState,
    UserRole,
)
from app.enums import InventoryReason
from app.models import Build, FileVersion, InventoryTxn, Job, Material, Printer, Ticket, User
from app.scheduler import SchedulerConfig, build_schedule, confirm_proposal

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
_n = [0]


def _uid():
    _n[0] += 1
    return _n[0]


def cfg(**kw):
    kw.setdefault("now", NOW)
    return SchedulerConfig(**kw)


def mk_printer(session, *, process, status=PrinterStatus.idle, loaded=None, caps=None, vol=(300, 300, 300)):
    mat = None
    if loaded:
        mat = Material(kind=MaterialKind.filament, spec=loaded, unit="g", qty_remaining=1000.0)
        session.add(mat)
        session.flush()
        session.add(InventoryTxn(material_id=mat.id, delta=1000.0, reason=InventoryReason.restock, at=NOW))
    p = Printer(name=f"{process.value}-{_uid()}", process=process, status=status,
                loaded_material=mat, capabilities=caps or {},
                build_volume_x=vol[0], build_volume_y=vol[1], build_volume_z=vol[2])
    session.add(p)
    session.flush()
    return p


def mk_job(session, *, process, material=None, priority=Priority.normal, deadline=None,
           queued_hours_ago=1.0, bbox=(20, 20, 10), est=10.0, unit="g", title="part"):
    req = User(username=f"r{_uid()}", display_name="r", role=UserRole.requester)
    t = Ticket(requester=req, title=title, target_process=process, material_pref=material,
               priority=priority, deadline=deadline)
    fv = FileVersion(ticket=t, version_no=1, filename="f.stl", blob_key="k",
                     bbox_x=bbox[0], bbox_y=bbox[1], bbox_z=bbox[2],
                     est_material_qty=est, est_material_unit=unit)
    t.current_file_version = fv
    j = Job(ticket=t, queue_state=QueueState.queued, queued_at=NOW - timedelta(hours=queued_hours_ago),
            created_at=NOW - timedelta(hours=queued_hours_ago))
    session.add_all([req, t, fv, j])
    session.flush()
    return j


def _bucket(view, printer_id):
    return next(b for b in view.buckets if b.printer_id == printer_id)


def _proposal(view, printer_id):
    return next((p for p in view.proposals if p.printer_id == printer_id), None)


# ============================================================== 1. capability partition
def test_capability_partition(session):
    fdm = mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    sla = mk_printer(session, process=ProcessType.SLA, loaded="Clear V4")
    fdm_small = mk_printer(session, process=ProcessType.FDM, loaded="PETG", vol=(30, 30, 30))
    fdm_open = mk_printer(session, process=ProcessType.FDM, loaded="PETG")  # not enclosed

    j_petg = mk_job(session, process=ProcessType.FDM, material="PETG", bbox=(40, 40, 20))
    j_pa12 = mk_job(session, process=ProcessType.FDM, material="PA12-CF", bbox=(40, 40, 20))

    view = build_schedule(session, cfg())

    fdm_ids = {r.job_id for r in _bucket(view, fdm.id).next_up}
    assert j_petg.id in fdm_ids                       # process + material + fit OK
    assert j_petg.id not in {r.job_id for r in _bucket(view, sla.id).next_up}  # wrong process
    assert j_petg.id not in {r.job_id for r in _bucket(view, fdm_small.id).next_up}  # too big to fit
    # PA12-CF needs an enclosure -> excluded from the open FDM printers, present nowhere here
    assert j_pa12.id not in {r.job_id for r in _bucket(view, fdm_open.id).next_up}


def test_swap_eligibility_toggle(session):
    # printer loaded with PA12-CF but capable of PETG; a PETG job needs a swap.
    p = mk_printer(session, process=ProcessType.FDM, loaded="PA12-CF",
                   caps={"enclosed": True, "materials": ["PA12-CF", "PETG"]})
    j = mk_job(session, process=ProcessType.FDM, material="PETG")

    v_on = build_schedule(session, cfg(allow_swaps=True))
    ranked = _bucket(v_on, p.id).next_up
    assert [r.job_id for r in ranked] == [j.id]
    assert ranked[0].needs_swap is True               # eligible, but flagged as a swap

    v_off = build_schedule(session, cfg(allow_swaps=False))
    assert _bucket(v_off, p.id).next_up == []          # swaps off -> not eligible


# ============================================================== 2. ordering + age-boost
def test_ordering_and_age_boost(session):
    p = mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    jA = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.critical, queued_hours_ago=1, title="A")
    jB = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.high, deadline=TODAY + timedelta(days=1), queued_hours_ago=1, title="B")
    jC = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.normal, deadline=TODAY + timedelta(days=2), queued_hours_ago=1, title="C")
    jD = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.low, queued_hours_ago=100, title="D")  # >72h -> boost to normal
    jE = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.low, queued_hours_ago=1, title="E")

    ranked = _bucket(build_schedule(session, cfg()), p.id).next_up
    assert [r.job_id for r in ranked] == [jA.id, jB.id, jC.id, jD.id, jE.id]

    by_id = {r.job_id: r for r in ranked}
    assert by_id[jD.id].boosted is True and by_id[jD.id].effective_priority == "normal"
    assert by_id[jC.id].boosted is False  # jC normal(dated) sorts before jD low-boosted(undated)
    assert by_id[jE.id].boosted is False

    # boost disabled -> jD falls behind jE? both low; jD older -> still before jE, but now AFTER nothing changes
    ranked_off = _bucket(build_schedule(session, cfg(age_boost_enabled=False)), p.id).next_up
    # with no boost, jD and jE are both 'low'; order among them is age (jD older first)
    ids_off = [r.job_id for r in ranked_off]
    assert ids_off.index(jD.id) > ids_off.index(jC.id)   # jD no longer lifted above other lows? it drops to low tier
    assert ids_off[-2:] == [jD.id, jE.id]                # the two lows trail, oldest-first


# ============================================================== 3. no preemption
def test_no_preemption(session):
    p = mk_printer(session, process=ProcessType.FDM, loaded="PETG", status=PrinterStatus.printing)
    running = Build(printer=p, process=ProcessType.FDM, current_stage="printing", status=BuildStatus.running)
    session.add(running)
    session.flush()
    j_crit = mk_job(session, process=ProcessType.FDM, material="PETG", priority=Priority.critical)

    view = build_schedule(session, cfg())
    bucket = _bucket(view, p.id)
    assert bucket.busy is True
    assert bucket.running_build_id == running.id
    assert bucket.next_up[0].job_id == j_crit.id        # Critical goes front-of-next-up
    assert _proposal(view, p.id) is None                # but NO proposal touches the busy printer


# ============================================================== 4. build assembly
def test_build_assembly_groups_within_fill_cap(session):
    # SLS plate 200x200 = 40000; cap 0.8 -> 32000. Each part 100x100 = 10000.
    p = mk_printer(session, process=ProcessType.SLS, loaded="PA12", vol=(200, 200, 330))
    s = [mk_job(session, process=ProcessType.SLS, material="PA12", bbox=(100, 100, 40),
                queued_hours_ago=10 - i, title=f"s{i}") for i in range(4)]
    other_mat = mk_job(session, process=ProcessType.SLS, material="PA11", bbox=(50, 50, 40), queued_hours_ago=1)
    too_big = mk_job(session, process=ProcessType.SLS, material="PA12", bbox=(500, 500, 40), queued_hours_ago=1)

    prop = _proposal(build_schedule(session, cfg()), p.id)
    assert prop is not None and prop.parts == 3          # anchor + 2 within cap; 4th overflows
    assert prop.fill_pct == pytest.approx(0.75)
    assert other_mat.id not in prop.job_ids             # different material never batched
    assert too_big.id not in prop.job_ids               # never eligible (volume fit)
    assert prop.fill_pct <= prop.fill_cap_pct


def test_batching_off_is_one_job_per_build(session):
    p = mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    [mk_job(session, process=ProcessType.FDM, material="PETG", queued_hours_ago=h, title=f"j{h}") for h in (3, 2, 1)]
    prop = _proposal(build_schedule(session, cfg()), p.id)   # FDM batching default OFF
    assert prop is not None and prop.parts == 1


# ============================================================== 5. material annotation
def test_material_shortfall_flagged_but_still_proposable(session):
    p = mk_printer(session, process=ProcessType.FDM, status=PrinterStatus.idle, loaded="PETG")
    # override the auto-created loaded material's stock to be tight + thresholded
    petg = p.loaded_material
    petg.qty_remaining = 15.0
    petg.reorder_threshold = 100.0
    session.flush()
    mk_job(session, process=ProcessType.FDM, material="PETG", est=22.0, unit="g")  # 22 > 15

    prop = _proposal(build_schedule(session, cfg()), p.id)
    assert prop is not None                              # STILL proposable — never blocked
    assert prop.material.fits is False
    assert prop.material.shortfall == pytest.approx(7.0)
    assert prop.material.low_material is True
    assert "short by" in prop.material.note


def test_material_fits_annotation(session):
    p = mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    p.loaded_material.qty_remaining = 500.0
    session.flush()
    mk_job(session, process=ProcessType.FDM, material="PETG", est=22.0)
    prop = _proposal(build_schedule(session, cfg()), p.id)
    assert prop.material.fits is True and prop.material.shortfall == 0.0
    assert "fits stock" in prop.material.note


# ============================================================== 6. determinism
def test_determinism_same_inputs_same_order(session):
    mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    for i in range(6):
        mk_job(session, process=ProcessType.FDM, material="PETG",
               priority=Priority.normal, queued_hours_ago=5, title=f"d{i}")  # all identical but id
    v1 = build_schedule(session, cfg())
    v2 = build_schedule(session, cfg())
    assert [ [r.job_id for r in b.next_up] for b in v1.buckets ] == \
           [ [r.job_id for r in b.next_up] for b in v2.buckets ]
    assert [p.job_ids for p in v1.proposals] == [p.job_ids for p in v2.proposals]


# ============================================================== operator confirm
def test_confirm_proposal_materializes_and_starts(session):
    p = mk_printer(session, process=ProcessType.FDM, loaded="PETG")
    j = mk_job(session, process=ProcessType.FDM, material="PETG")
    view = build_schedule(session, cfg())
    prop = _proposal(view, p.id)
    assert prop is not None

    chosen = [session.get(Job, jid) for jid in prop.job_ids]
    build = confirm_proposal(session, p, chosen, actor=None)
    session.commit()

    assert build.current_stage == "printing"
    assert build.status == BuildStatus.running
    assert j.build_id == build.id
    assert j.queue_state == QueueState.scheduled
    assert j.file_version_id is not None                 # R3 version pinned
    assert p.status == PrinterStatus.printing            # human-updated, not telemetry
    assert reconcile_all(session) == []

    # the job is no longer Queued -> drops out of the next schedule (no double-scheduling)
    assert _proposal(build_schedule(session, cfg()), p.id) is None
