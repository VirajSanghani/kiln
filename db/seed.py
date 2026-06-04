"""Seed the KILN dev database.

Idempotent: TRUNCATEs the domain tables (Postgres CASCADE) then inserts a coherent
cross-process dataset that deliberately exercises the hard cases:

  * a SHARED multi-Job Build that is Done, with ONE Job overridden to qc_rejected
    (G1 clause 1 beating clause 2 — a per-part failure on an otherwise-good plate);
  * a re-printed ticket (v2 Failed on an old Build, v3 Printing now) to exercise the
    R4 "least-advanced non-terminal job" rollup;
  * pre-Build Jobs in submitted / queued / scheduled and a cancelled Job (G1 clause 3);
  * an active-stage Build (FDM Printing) and a passive-stage Build (SLS Cooldown);
  * materials with and without reorder thresholds (R6).

Every mutable column is written in the SAME transaction as its events via the audit
folds (recompute_*), so `python -m app.audit` reconciles clean immediately after.

Run:  docker compose exec api python /app/db/seed.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

# Make `app` importable whether run as /app/db/seed.py (container) or locally.
sys.path.insert(0, "/app/api")

from sqlalchemy import text

from app.audit import (
    reconcile_all,
    recompute_build_columns,
    recompute_job_columns,
    recompute_material_qty,
)
from app.db import SessionLocal
from app.derivation import job_effective_status, ticket_status
from app.enums import (
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
from app.security import hash_password
from app.models import (
    Build,
    FileVersion,
    InventoryTxn,
    Job,
    Material,
    Notification,
    Printer,
    StageEvent,
    Ticket,
    User,
)

NOW = datetime.now(timezone.utc)


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def ahead(days: int):
    return (NOW + timedelta(days=days)).date()


def opened(days: int):
    return (NOW - timedelta(days=days)).date()


TABLES = [
    "notifications", "stage_events", "inventory_txns", "jobs", "builds",
    "file_versions", "tickets", "printers", "materials", "users",
]


def wipe(session):
    session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


def ev(session, *, to, at, frm=None, build=None, job=None, actor=None, note=None):
    e = StageEvent(from_stage=frm, to_stage=to, at=at, note=note)
    e.build = build
    e.job = job
    e.actor = actor
    session.add(e)
    return e


def txn(session, material, delta, reason, at, *, build=None, actor=None, note=None):
    t = InventoryTxn(delta=delta, reason=reason, at=at, note=note)
    t.material = material
    t.build = build
    t.actor = actor
    session.add(t)
    return t


def queue_chain(session, job, *, through: QueueState, actor, start: datetime):
    """Emit submitted -> ... -> `through` pre-Build events (build_id NULL)."""
    order = [QueueState.submitted, QueueState.queued, QueueState.scheduled]
    prev = None
    t = start
    for st in order:
        ev(session, frm=prev, to=st.value, at=t, job=job, actor=actor)
        prev = st.value
        t = t + timedelta(minutes=1)
        if st == through:
            break


def build():
    session = SessionLocal()
    try:
        wipe(session)

        # ---- people (demo password = "<username>-pw", e.g. rk-pw / ana-pw) ----
        rk = User(username="rk", display_name="Riley K.", role=UserRole.operator, password_hash=hash_password("rk-pw"))
        sam = User(username="sam", display_name="Sam O.", role=UserRole.operator, password_hash=hash_password("sam-pw"))
        ana = User(username="ana", display_name="Ana P.", role=UserRole.requester, password_hash=hash_password("ana-pw"))
        ben = User(username="ben", display_name="Ben T.", role=UserRole.requester, password_hash=hash_password("ben-pw"))
        session.add_all([rk, sam, ana, ben])

        # ---- materials (some with reorder thresholds, some without — R6) ----
        m_petg = Material(kind=MaterialKind.filament, spec="PETG", color="grey", unit="g",
                          reorder_threshold=150, lot="A12", opened_date=opened(41),
                          drying_state=DryingState.dry)
        m_pa12cf = Material(kind=MaterialKind.filament, spec="PA12-CF", color="black", unit="g",
                            reorder_threshold=300, lot="C7", opened_date=opened(12),
                            drying_state=DryingState.needs_drying)
        m_tpu = Material(kind=MaterialKind.filament, spec="TPU", color="clear", unit="g",
                         reorder_threshold=150, lot="T3", opened_date=opened(60),
                         drying_state=DryingState.dry)
        m_clear = Material(kind=MaterialKind.resin, spec="Clear V4", color="clear", unit="mL",
                           reorder_threshold=None, lot="R9", opened_date=opened(5),
                           shelf_life_days=30)               # no threshold (R6)
        m_tough = Material(kind=MaterialKind.resin, spec="Tough 2000", color="amber", unit="mL",
                           reorder_threshold=100, lot="R4", opened_date=opened(88),
                           shelf_life_days=60)
        m_powder = Material(kind=MaterialKind.powder, spec="PA12", color="white", unit="g",
                            reorder_threshold=1000, virgin_qty=1820, used_qty=640)
        m_agent = Material(kind=MaterialKind.agent, spec="MJF fusing agent", unit="mL",
                           reorder_threshold=None)            # no threshold (R6)
        session.add_all([m_petg, m_pa12cf, m_tpu, m_clear, m_tough, m_powder, m_agent])

        # initial stock + a hand-adjust + (later) a consume on the Done build
        txn(session, m_petg, +180, InventoryReason.restock, ago(days=41), actor=rk)
        txn(session, m_pa12cf, +480, InventoryReason.restock, ago(days=12), actor=rk)
        txn(session, m_tpu, +100, InventoryReason.restock, ago(days=60), actor=rk)
        txn(session, m_tpu, -10, InventoryReason.adjust, ago(days=2), actor=sam, note="spool spillage")
        txn(session, m_clear, +240, InventoryReason.restock, ago(days=5), actor=rk)
        txn(session, m_tough, +60, InventoryReason.restock, ago(days=88), actor=rk)
        txn(session, m_powder, +2460, InventoryReason.restock, ago(days=20), actor=rk)
        txn(session, m_agent, +1100, InventoryReason.restock, ago(days=20), actor=rk)

        # ---- printers across all 4 processes ----
        p_mk4 = Printer(name="Prusa-MK4 #1", process=ProcessType.FDM, status=PrinterStatus.printing,
                        build_volume_x=250, build_volume_y=210, build_volume_z=220,
                        loaded_material=m_petg, capabilities={"enclosed": False, "direct_drive": False})
        p_x1c = Printer(name="Bambu-X1C #1", process=ProcessType.FDM, status=PrinterStatus.idle,
                        build_volume_x=256, build_volume_y=256, build_volume_z=256,
                        loaded_material=m_pa12cf,
                        capabilities={"enclosed": True, "direct_drive": False, "materials": ["PA12-CF", "PETG"]})
        p_form3 = Printer(name="Form3 #1", process=ProcessType.SLA, status=PrinterStatus.idle,
                          build_volume_x=145, build_volume_y=145, build_volume_z=185,
                          loaded_material=m_clear, capabilities={})
        p_eos = Printer(name="EOS-P110", process=ProcessType.SLS, status=PrinterStatus.idle,
                        build_volume_x=200, build_volume_y=200, build_volume_z=330,
                        loaded_material=m_powder, capabilities={})
        p_mjf = Printer(name="HP-MJF-4200", process=ProcessType.MJF, status=PrinterStatus.idle,
                        build_volume_x=380, build_volume_y=284, build_volume_z=380,
                        loaded_material=m_powder, capabilities={"agent": "MJF fusing agent"})
        session.add_all([p_mk4, p_x1c, p_form3, p_eos, p_mjf])

        # ===============================================================================
        # T1 — re-printed ticket (R4): v2 Failed on old Build, v3 Printing now.
        # ===============================================================================
        t1 = Ticket(requester=ana, title="motor bracket", target_process=ProcessType.FDM,
                    material_pref="PETG", priority=Priority.critical, deadline=ahead(1),
                    created_at=ago(days=3))
        fv1 = FileVersion(ticket=t1, version_no=1, filename="bracket.stl", blob_key="dev/t1/v1.stl",
                          slicer_name="PrusaSlicer", est_time_seconds=6000, est_material_qty=21,
                          est_material_unit="g", bbox_x=60, bbox_y=40, bbox_z=12, created_at=ago(days=3))
        fv2 = FileVersion(ticket=t1, version_no=2, filename="bracket.stl", blob_key="dev/t1/v2.stl",
                          slicer_name="PrusaSlicer", est_time_seconds=6720, est_material_qty=23,
                          est_material_unit="g", bbox_x=60, bbox_y=40, bbox_z=12, created_at=ago(days=2))
        fv3 = FileVersion(ticket=t1, version_no=3, filename="bracket.stl", blob_key="dev/t1/v3.stl",
                          slicer_name="PrusaSlicer", est_time_seconds=6480, est_material_qty=22,
                          est_material_unit="g", bbox_x=60, bbox_y=40, bbox_z=12, created_at=ago(hours=4))
        t1.current_file_version = fv3
        session.add_all([t1, fv1, fv2, fv3])

        # --- old FAILED FDM build carrying T1.v2 ---
        b_old = Build(printer=p_mk4, process=ProcessType.FDM, material=m_petg,
                      current_stage="printing", note="warped off the bed",
                      created_at=ago(days=2), started_at=ago(days=2))
        j_old = Job(ticket=t1, file_version=fv2, build=b_old, created_at=ago(days=2),
                    queued_at=ago(days=2), allocated_unit="g")
        session.add_all([b_old, j_old])
        queue_chain(session, j_old, through=QueueState.scheduled, actor=rk, start=ago(days=2))
        ev(session, to="printing", at=ago(days=2) + timedelta(minutes=5), build=b_old, actor=rk,
           note="plate started")
        ev(session, frm="printing", to="failed", at=ago(days=2) + timedelta(hours=1), build=b_old,
           actor=rk, note="print detached / warp")
        # build-level failure -> j_old has NO own override; it inherits 'failed' (G1 clause 2)

        # --- current ACTIVE-stage FDM build (Printing) carrying T1.v3 + a second job ---
        b117 = Build(printer=p_mk4, process=ProcessType.FDM, material=m_petg,
                     current_stage="printing", created_at=ago(hours=3), started_at=ago(hours=2, minutes=30))
        j_new = Job(ticket=t1, file_version=fv3, build=b117, created_at=ago(hours=4),
                    queued_at=ago(hours=4))
        session.add_all([b117, j_new])

        t2 = Ticket(requester=ben, title="fan mount", target_process=ProcessType.FDM,
                    material_pref="PETG", priority=Priority.high, deadline=ahead(2), created_at=ago(hours=6))
        fv_t2 = FileVersion(ticket=t2, version_no=1, filename="mount.stl", blob_key="dev/t2/v1.stl",
                            slicer_name="PrusaSlicer", est_time_seconds=5400, est_material_qty=18,
                            est_material_unit="g", bbox_x=50, bbox_y=50, bbox_z=20, created_at=ago(hours=6))
        t2.current_file_version = fv_t2
        j_mount = Job(ticket=t2, file_version=fv_t2, build=b117, created_at=ago(hours=5),
                      queued_at=ago(hours=5))
        session.add_all([t2, fv_t2, j_mount])

        for j in (j_new, j_mount):
            queue_chain(session, j, through=QueueState.scheduled, actor=rk, start=j.queued_at)
        ev(session, to="printing", at=ago(hours=2, minutes=30), build=b117, actor=rk, note="plate started")

        # ===============================================================================
        # B_done — SHARED multi-Job FDM Build, completed (Done), with ONE qc_rejected job.
        # Jobs come from THREE different tickets/requesters (a batched plate). G1 clause 1.
        # ===============================================================================
        t3 = Ticket(requester=ana, title="cable clip", target_process=ProcessType.FDM,
                    material_pref="PA12-CF", priority=Priority.normal, deadline=ahead(5), created_at=ago(days=1))
        fv_t3 = FileVersion(ticket=t3, version_no=1, filename="clip.stl", blob_key="dev/t3/v1.stl",
                            slicer_name="Cura", est_time_seconds=3600, est_material_qty=9,
                            est_material_unit="g", bbox_x=30, bbox_y=20, bbox_z=10, created_at=ago(days=1))
        t3.current_file_version = fv_t3
        t4 = Ticket(requester=ben, title="gusset", target_process=ProcessType.FDM,
                    material_pref="PA12-CF", priority=Priority.normal, deadline=ahead(5), created_at=ago(days=1))
        fv_t4 = FileVersion(ticket=t4, version_no=1, filename="gusset.stl", blob_key="dev/t4/v1.stl",
                            slicer_name="Cura", est_time_seconds=4200, est_material_qty=11,
                            est_material_unit="g", bbox_x=40, bbox_y=30, bbox_z=15, created_at=ago(days=1))
        t4.current_file_version = fv_t4
        t5 = Ticket(requester=ana, title="mounting tab", target_process=ProcessType.FDM,
                    material_pref="PA12-CF", priority=Priority.high, deadline=ahead(2), created_at=ago(days=1))
        fv_t5 = FileVersion(ticket=t5, version_no=1, filename="tab.stl", blob_key="dev/t5/v1.stl",
                            slicer_name="Cura", est_time_seconds=3000, est_material_qty=8,
                            est_material_unit="g", bbox_x=25, bbox_y=25, bbox_z=8, created_at=ago(days=1))
        t5.current_file_version = fv_t5
        session.add_all([t3, fv_t3, t4, fv_t4, t5, fv_t5])

        b_done = Build(printer=p_x1c, process=ProcessType.FDM, material=m_pa12cf,
                       current_stage="done", created_at=ago(days=1),
                       started_at=ago(days=1), completed_at=ago(hours=8))
        j_t3 = Job(ticket=t3, file_version=fv_t3, build=b_done, qc_outcome=QCOutcome.passed,
                   allocated_qty=20, allocated_unit="g", created_at=ago(days=1), queued_at=ago(days=1))
        j_t4 = Job(ticket=t4, file_version=fv_t4, build=b_done, qc_outcome=QCOutcome.passed,
                   allocated_qty=20, allocated_unit="g", created_at=ago(days=1), queued_at=ago(days=1))
        # the rejected part — terminal override beats the Build being Done
        j_t5 = Job(ticket=t5, file_version=fv_t5, build=b_done, qc_outcome=QCOutcome.failed,
                   fail_reason="warped at QC", allocated_qty=20, allocated_unit="g",
                   created_at=ago(days=1), queued_at=ago(days=1))
        session.add_all([b_done, j_t3, j_t4, j_t5])

        for j in (j_t3, j_t4, j_t5):
            queue_chain(session, j, through=QueueState.scheduled, actor=rk, start=j.queued_at)
        base = ago(days=1) + timedelta(minutes=10)
        ev(session, to="printing", at=base, build=b_done, actor=rk, note="batched plate started")
        ev(session, frm="printing", to="support_removal", at=base + timedelta(hours=12), build=b_done, actor=sam)
        ev(session, frm="support_removal", to="qc", at=base + timedelta(hours=13), build=b_done, actor=sam)
        ev(session, frm="qc", to="done", at=base + timedelta(hours=14), build=b_done, actor=sam,
           note="2/3 passed")
        # per-part override for the failed tab
        ev(session, frm="qc", to="qc_rejected", at=base + timedelta(hours=13, minutes=30),
           build=b_done, job=j_t5, actor=sam, note="warped at QC")
        # material decrements once per Build, on Done; allocated across the 3 jobs
        txn(session, m_pa12cf, -60, InventoryReason.consume, b_done.completed_at, build=b_done,
            actor=sam, note="20g x 3 parts")

        # ===============================================================================
        # PASSIVE-stage SLS Build (Cooldown) — batched (2 jobs), not yet Done.
        # ===============================================================================
        t6 = Ticket(requester=ana, title="gear set", target_process=ProcessType.SLS,
                    material_pref="PA12", priority=Priority.normal, deadline=ahead(6), created_at=ago(hours=20))
        fv_t6 = FileVersion(ticket=t6, version_no=1, filename="gears.stl", blob_key="dev/t6/v1.stl",
                            slicer_name="manual", est_time_seconds=28800, est_material_qty=140,
                            est_material_unit="g", bbox_x=80, bbox_y=80, bbox_z=40, created_at=ago(hours=20))
        t6.current_file_version = fv_t6
        t7 = Ticket(requester=ben, title="pulley", target_process=ProcessType.SLS,
                    material_pref="PA12", priority=Priority.normal, deadline=ahead(6), created_at=ago(hours=20))
        fv_t7 = FileVersion(ticket=t7, version_no=1, filename="pulley.stl", blob_key="dev/t7/v1.stl",
                            slicer_name="manual", est_time_seconds=21600, est_material_qty=95,
                            est_material_unit="g", bbox_x=60, bbox_y=60, bbox_z=50, created_at=ago(hours=20))
        t7.current_file_version = fv_t7
        session.add_all([t6, fv_t6, t7, fv_t7])

        b_sls = Build(printer=p_eos, process=ProcessType.SLS, material=m_powder,
                      current_stage="cooldown", created_at=ago(hours=14), started_at=ago(hours=13))
        j_g1 = Job(ticket=t6, file_version=fv_t6, build=b_sls, created_at=ago(hours=18), queued_at=ago(hours=18))
        j_g2 = Job(ticket=t7, file_version=fv_t7, build=b_sls, created_at=ago(hours=18), queued_at=ago(hours=18))
        session.add_all([b_sls, j_g1, j_g2])
        for j in (j_g1, j_g2):
            queue_chain(session, j, through=QueueState.scheduled, actor=rk, start=j.queued_at)
        ev(session, to="printing", at=ago(hours=13), build=b_sls, actor=rk)
        ev(session, frm="printing", to="cooldown", at=ago(hours=2), build=b_sls, actor=rk,
           note="chamber cooling (passive)")

        # ===============================================================================
        # ACTIVE-stage SLA Build (Wash) and ACTIVE-stage MJF Build (Depowder).
        # ===============================================================================
        t8 = Ticket(requester=ana, title="lens housing", target_process=ProcessType.SLA,
                    material_pref="Clear V4", priority=Priority.normal, deadline=ahead(7), created_at=ago(hours=10))
        fv_t8 = FileVersion(ticket=t8, version_no=1, filename="lens.stl", blob_key="dev/t8/v1.stl",
                            slicer_name="PreForm", est_time_seconds=14400, est_material_qty=45,
                            est_material_unit="mL", bbox_x=40, bbox_y=40, bbox_z=60, created_at=ago(hours=10))
        t8.current_file_version = fv_t8
        b_sla = Build(printer=p_form3, process=ProcessType.SLA, material=m_clear,
                      current_stage="wash", created_at=ago(hours=9), started_at=ago(hours=8))
        j_lens = Job(ticket=t8, file_version=fv_t8, build=b_sla, created_at=ago(hours=9), queued_at=ago(hours=9))
        session.add_all([t8, fv_t8, b_sla, j_lens])
        queue_chain(session, j_lens, through=QueueState.scheduled, actor=rk, start=j_lens.queued_at)
        ev(session, to="printing", at=ago(hours=8), build=b_sla, actor=rk)
        ev(session, frm="printing", to="drain", at=ago(hours=3), build=b_sla, actor=sam)
        ev(session, frm="drain", to="wash", at=ago(hours=1), build=b_sla, actor=sam, note="IPA wash")

        t9 = Ticket(requester=ben, title="enclosure clip", target_process=ProcessType.MJF,
                    material_pref="PA12", priority=Priority.normal, deadline=ahead(6), created_at=ago(hours=16))
        fv_t9 = FileVersion(ticket=t9, version_no=1, filename="clip2.stl", blob_key="dev/t9/v1.stl",
                            slicer_name="manual", est_time_seconds=18000, est_material_qty=70,
                            est_material_unit="g", bbox_x=70, bbox_y=40, bbox_z=30, created_at=ago(hours=16))
        t9.current_file_version = fv_t9
        b_mjf = Build(printer=p_mjf, process=ProcessType.MJF, material=m_powder,
                      current_stage="depowder", created_at=ago(hours=12), started_at=ago(hours=11))
        j_mjf = Job(ticket=t9, file_version=fv_t9, build=b_mjf, created_at=ago(hours=15), queued_at=ago(hours=15))
        session.add_all([t9, fv_t9, b_mjf, j_mjf])
        queue_chain(session, j_mjf, through=QueueState.scheduled, actor=rk, start=j_mjf.queued_at)
        ev(session, to="printing", at=ago(hours=11), build=b_mjf, actor=rk)
        ev(session, frm="printing", to="cooldown", at=ago(hours=4), build=b_mjf, actor=rk)
        ev(session, frm="cooldown", to="depowder", at=ago(hours=1), build=b_mjf, actor=sam,
           note="bead-blast depowder")

        # ===============================================================================
        # Pre-Build Jobs (G1 clause 3): submitted / queued (boost candidate) / scheduled,
        # plus a cancelled Job.
        # ===============================================================================
        t10 = Ticket(requester=ben, title="spacer", target_process=ProcessType.FDM,
                     material_pref="PETG", priority=Priority.low, deadline=None, created_at=ago(days=3))
        fv_t10 = FileVersion(ticket=t10, version_no=1, filename="spacer.stl", blob_key="dev/t10/v1.stl",
                             slicer_name="PrusaSlicer", est_time_seconds=1800, est_material_qty=5,
                             est_material_unit="g", bbox_x=20, bbox_y=20, bbox_z=5, created_at=ago(days=3))
        t10.current_file_version = fv_t10
        j_spacer = Job(ticket=t10, created_at=ago(days=3), queued_at=ago(days=3))  # waited 3d -> boost candidate
        session.add_all([t10, fv_t10, j_spacer])
        queue_chain(session, j_spacer, through=QueueState.queued, actor=rk, start=ago(days=3))

        t11 = Ticket(requester=ana, title="lens cap", target_process=ProcessType.SLA,
                     material_pref="Clear V4", priority=Priority.normal, deadline=ahead(3), created_at=ago(hours=5))
        fv_t11 = FileVersion(ticket=t11, version_no=1, filename="cap.stl", blob_key="dev/t11/v1.stl",
                             slicer_name="PreForm", est_time_seconds=7200, est_material_qty=20,
                             est_material_unit="mL", bbox_x=30, bbox_y=30, bbox_z=15, created_at=ago(hours=5))
        t11.current_file_version = fv_t11
        j_cap = Job(ticket=t11, created_at=ago(hours=5), queued_at=ago(hours=4))
        session.add_all([t11, fv_t11, j_cap])
        queue_chain(session, j_cap, through=QueueState.scheduled, actor=rk, start=ago(hours=4))

        t12 = Ticket(requester=ben, title="vent grille", target_process=ProcessType.FDM,
                     material_pref="PETG", priority=Priority.normal, deadline=None, created_at=ago(hours=1))
        fv_t12 = FileVersion(ticket=t12, version_no=1, filename="vent.stl", blob_key="dev/t12/v1.stl",
                             slicer_name="PrusaSlicer", est_time_seconds=4000, est_material_qty=14,
                             est_material_unit="g", bbox_x=80, bbox_y=80, bbox_z=6, created_at=ago(hours=1))
        t12.current_file_version = fv_t12
        j_vent = Job(ticket=t12, created_at=ago(hours=1))  # just submitted
        session.add_all([t12, fv_t12, j_vent])
        ev(session, to="submitted", at=ago(hours=1), job=j_vent, actor=ben)

        t13 = Ticket(requester=ana, title="obsolete jig", target_process=ProcessType.FDM,
                     material_pref="PETG", priority=Priority.low, deadline=None, created_at=ago(days=4))
        fv_t13 = FileVersion(ticket=t13, version_no=1, filename="jig.stl", blob_key="dev/t13/v1.stl",
                             slicer_name="PrusaSlicer", est_time_seconds=9000, est_material_qty=30,
                             est_material_unit="g", bbox_x=120, bbox_y=80, bbox_z=20, created_at=ago(days=4))
        t13.current_file_version = fv_t13
        j_cancel = Job(ticket=t13, created_at=ago(days=4), queued_at=ago(days=4))
        session.add_all([t13, fv_t13, j_cancel])
        ev(session, to="submitted", at=ago(days=4), job=j_cancel, actor=ana)
        ev(session, frm="submitted", to="cancelled", at=ago(days=3), job=j_cancel, actor=ana,
           note="design superseded")

        # ===============================================================================
        # QUEUED BACKLOG — feeds the scheduler's capability buckets + proposals.
        # FDM jobs bucket onto the idle Bambu-X1C; SLS jobs batch onto the idle EOS.
        # ===============================================================================
        backlog: list[Job] = []

        def queued(title, requester, process, mat, prio, deadline_days, age_h, bbox, est, unit):
            tk = Ticket(requester=requester, title=title, target_process=process, material_pref=mat,
                        priority=prio, deadline=(ahead(deadline_days) if deadline_days is not None else None),
                        created_at=ago(hours=age_h))
            fv = FileVersion(ticket=tk, version_no=1, filename=f"{title.replace(' ', '_')}.stl",
                             blob_key=f"dev/q/{title}.stl", slicer_name="PrusaSlicer",
                             est_time_seconds=int(est * 120), est_material_qty=est, est_material_unit=unit,
                             bbox_x=bbox[0], bbox_y=bbox[1], bbox_z=bbox[2], created_at=ago(hours=age_h))
            tk.current_file_version = fv
            j = Job(ticket=tk, created_at=ago(hours=age_h), queued_at=ago(hours=age_h))
            session.add_all([tk, fv, j])
            queue_chain(session, j, through=QueueState.queued, actor=rk, start=ago(hours=age_h))
            backlog.append(j)
            return j

        queued("heatsink bracket", ana, ProcessType.FDM, "PA12-CF", Priority.critical, 1, 2, (60, 40, 20), 25, "g")
        queued("sensor mount", ben, ProcessType.FDM, "PA12-CF", Priority.high, 3, 5, (50, 50, 25), 30, "g")
        queued("washer x10", ana, ProcessType.FDM, "PA12-CF", Priority.normal, 5, 8, (30, 30, 8), 12, "g")
        queued("jig adapter", ben, ProcessType.FDM, "PA12-CF", Priority.low, None, 100, (80, 60, 20), 40, "g")  # boost
        queued("bevel gear", ana, ProcessType.SLS, "PA12", Priority.normal, 6, 6, (80, 80, 40), 120, "g")
        queued("spur gear", ben, ProcessType.SLS, "PA12", Priority.normal, 6, 5, (60, 60, 40), 90, "g")
        queued("bushing set", ana, ProcessType.SLS, "PA12", Priority.normal, 6, 4, (50, 50, 30), 60, "g")

        def submitted(title, requester, process, mat, prio, age_h, bbox, est, unit):
            tk = Ticket(requester=requester, title=title, target_process=process, material_pref=mat,
                        priority=prio, created_at=ago(hours=age_h))
            fv = FileVersion(ticket=tk, version_no=1, filename=f"{title.replace(' ', '_')}.stl",
                             blob_key=f"dev/s/{title}.stl", slicer_name="PrusaSlicer",
                             est_time_seconds=int(est * 120), est_material_qty=est, est_material_unit=unit,
                             bbox_x=bbox[0], bbox_y=bbox[1], bbox_z=bbox[2], created_at=ago(hours=age_h))
            tk.current_file_version = fv
            j = Job(ticket=tk, created_at=ago(hours=age_h))
            session.add_all([tk, fv, j])
            ev(session, to="submitted", at=ago(hours=age_h), job=j, actor=requester)
            backlog.append(j)

        submitted("drone arm", ana, ProcessType.FDM, "PETG", Priority.high, 2, (90, 30, 12), 28, "g")
        submitted("bearing jig", ben, ProcessType.SLS, "PA12", Priority.normal, 3, (70, 70, 35), 85, "g")
        submitted("face plate", ana, ProcessType.SLA, "Clear V4", Priority.normal, 1, (50, 50, 8), 18, "mL")

        # ---- notifications (a couple, generated on requester-relevant events) ----
        session.add_all([
            Notification(user=ana, ticket=t5, job=j_t5, kind=NotificationKind.failed,
                         message="Your part 'mounting tab' was rejected at QC (warped)."),
            Notification(user=ben, ticket=t4, job=j_t4, kind=NotificationKind.ready_for_pickup,
                         message="Your part 'gusset' is done and ready for pickup."),
        ])

        # -------------------------------------------------------------------------------
        # SAME-TRANSACTION column writes: fold the events we just appended into the
        # mutable convenience columns, before commit.
        # -------------------------------------------------------------------------------
        all_builds = [b_old, b117, b_done, b_sls, b_sla, b_mjf]
        all_jobs = [j_old, j_new, j_mount, j_t3, j_t4, j_t5, j_g1, j_g2, j_lens, j_mjf,
                    j_spacer, j_cap, j_vent, j_cancel] + backlog
        all_materials = [m_petg, m_pa12cf, m_tpu, m_clear, m_tough, m_powder, m_agent]
        session.flush()  # assign ids so event ordering ties are stable
        for b in all_builds:
            recompute_build_columns(b)
        for j in all_jobs:
            recompute_job_columns(j)
        for m in all_materials:
            recompute_material_qty(m)

        session.commit()

        # ---- report ----
        print("Seed committed.\n")
        _summary(session)

        discrepancies = reconcile_all(session)
        if discrepancies:
            print(f"\nRECONCILE FAILED — {len(discrepancies)}:")
            for d in discrepancies:
                print("  -", d)
            return 1
        print("\nRECONCILE OK — every mutable column matches fold(events).")
        return 0
    finally:
        session.close()


def _summary(session):
    from sqlalchemy import func, select
    counts = {}
    for name, model in [("users", User), ("printers", Printer), ("materials", Material),
                        ("tickets", Ticket), ("file_versions", FileVersion), ("jobs", Job),
                        ("builds", Build), ("stage_events", StageEvent),
                        ("inventory_txns", InventoryTxn), ("notifications", Notification)]:
        counts[name] = session.scalar(select(func.count()).select_from(model))
    print("Rows:", ", ".join(f"{k}={v}" for k, v in counts.items()))

    print("\nDerived status checks (G1 + R4):")
    b_done = session.scalar(select(Build).where(Build.current_stage == "done", Build.process == ProcessType.FDM))
    if b_done:
        print(f"  Build#{b_done.id} (Done, shared plate): "
              + ", ".join(f"Job#{j.id}->{job_effective_status(j)}" for j in b_done.jobs)
              + "   <- one qc_rejected overrides the Done build (G1 clause 1)")
    for title in ("motor bracket", "mounting tab", "spacer", "obsolete jig"):
        tk = session.scalar(select(Ticket).where(Ticket.title == title))
        if tk:
            print(f"  Ticket '{tk.title}': status={ticket_status(tk)} "
                  f"(jobs: {[job_effective_status(j) for j in tk.jobs]})")


if __name__ == "__main__":
    sys.exit(build())
