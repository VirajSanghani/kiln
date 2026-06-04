"""On-Done side effects + requester notifications.

CRITICAL invariant: material decrement + Job allocation are written into the SAME
session as the Build's done-transition. `stage_engine.advance` calls `on_build_done`
before returning, the caller commits once, so the done StageEvent + the InventoryTxn ride
a single commit — a crash between them cannot desync (reconcile would otherwise catch it).
"""
from __future__ import annotations

from .audit import recompute_material_qty
from .enums import InventoryReason, NotificationKind
from .models import InventoryTxn, Notification


def on_build_done(session, build) -> None:
    """Decrement material once per Build, allocate to Jobs, notify requesters. Same txn."""
    delivered = [j for j in build.jobs if j.terminal_status is None]  # parts that actually came off

    # project consumption from the versions that printed; allocate per Job
    total = 0.0
    for j in build.jobs:
        fv = j.file_version
        if fv and fv.est_material_qty is not None:
            total += fv.est_material_qty
            j.allocated_qty = fv.est_material_qty
            j.allocated_unit = fv.est_material_unit

    if build.material is not None and total > 0:
        txn = InventoryTxn(
            delta=-round(total, 3), reason=InventoryReason.consume,
            note=f"Build #{build.id} done — consumed across {len(build.jobs)} job(s)",
        )
        txn.material = build.material
        txn.build = build
        session.add(txn)
        session.flush()
        recompute_material_qty(build.material)   # column written in the SAME txn

    for j in delivered:
        n = Notification(
            kind=NotificationKind.ready_for_pickup,
            message=f"'{j.ticket.title}' is done and ready for pickup.",
        )
        n.user = j.ticket.requester
        n.ticket = j.ticket
        n.job = j
        session.add(n)


def notify_started(session, build) -> None:
    seen = set()
    for j in build.jobs:
        if j.ticket_id in seen:
            continue
        seen.add(j.ticket_id)
        n = Notification(kind=NotificationKind.started,
                         message=f"'{j.ticket.title}' has started printing on {build.printer.name}.")
        n.user = j.ticket.requester
        n.ticket = j.ticket
        n.job = j
        session.add(n)


def notify_failed(session, *, ticket, job, reason: str | None) -> None:
    n = Notification(kind=NotificationKind.failed,
                     message=f"'{ticket.title}' failed{f': {reason}' if reason else ''}.")
    n.user = ticket.requester
    n.ticket = ticket
    n.job = job
    session.add(n)
