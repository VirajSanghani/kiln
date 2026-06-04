"""Build assembly / batching — §6, §6.1, §7.

Group compatible Queued Jobs onto one proposed Build:
  - same process (guaranteed within a bucket), same material (one material per plate),
  - first-fit by FOOTPRINT AREA with a fill-% cap.

§6.1 honest limit: this is NOT a true 3D nester. It is greedy first-fit by bounding-box
footprint area with a fill cap — and it says so. A real 3D packer is a future seam.

§7 material annotation: project consumption from the Jobs' slicer estimates and annotate
"fits stock" / "short by Xg — flagged". Informs, never blocks; a short build is still
proposable, and a low-material printer is de-prioritized in proposals, never excluded.
"""
from __future__ import annotations

from sqlalchemy import func, select

from ..models import Material
from .capability import _part_file_version, capability_match
from .config import BuildProposal, MaterialAnnotation, SchedulerConfig


def _footprint(job) -> float | None:
    fv = _part_file_version(job)
    if fv is None or fv.bbox_x is None or fv.bbox_y is None:
        return None
    return fv.bbox_x * fv.bbox_y


def _plate_area(printer) -> float:
    return printer.build_volume_x * printer.build_volume_y


def _select_batch(ordered_jobs, printer, config: SchedulerConfig) -> list:
    """First job is the anchor; add later same-material jobs while within the fill cap."""
    anchor = ordered_jobs[0]
    batch_material = anchor.ticket.material_pref
    chosen = [anchor]
    cap_area = _plate_area(printer) * config.fill_pct_cap
    used = _footprint(anchor) or 0.0
    for j in ordered_jobs[1:]:
        if j.ticket.material_pref != batch_material:   # one material per plate
            continue
        fp = _footprint(j)
        if fp is not None and used + fp > cap_area:     # would overflow the cap — skip (try smaller later)
            continue
        chosen.append(j)
        used += fp or 0.0
    return chosen


def annotate_material(session, material_spec, jobs, config: SchedulerConfig) -> MaterialAnnotation:
    """§7 — projected consumption vs total stock of this spec (summed across lots)."""
    projected = 0.0
    unit = None
    for j in jobs:
        fv = _part_file_version(j)
        if fv and fv.est_material_qty is not None:
            projected += fv.est_material_qty
            unit = unit or fv.est_material_unit

    remaining = None
    threshold_breach = False
    if material_spec is not None:
        remaining = session.scalar(
            select(func.coalesce(func.sum(Material.qty_remaining), 0.0)).where(Material.spec == material_spec)
        )
        # below any same-spec reorder threshold? (R6: unset threshold never warns)
        min_thr = session.scalar(
            select(func.min(Material.reorder_threshold)).where(Material.spec == material_spec)
        )
        if min_thr is not None and remaining is not None and remaining < min_thr:
            threshold_breach = True

    fits = remaining is None or projected <= remaining
    shortfall = 0.0 if (remaining is None or fits) else round(projected - remaining, 3)
    low = (shortfall > 0) or threshold_breach
    u = unit or ""
    if remaining is None:
        note = f"projected {projected:g}{u} (no stock record)"
    elif fits:
        note = f"fits stock ({projected:g}{u} → {remaining - projected:g}{u} left)"
    else:
        note = f"short by {shortfall:g}{u} — flagged"
    return MaterialAnnotation(
        material_spec=material_spec, projected=round(projected, 3), unit=unit,
        remaining=remaining, fits=fits, shortfall=shortfall, low_material=low, note=note,
    )


def propose_for_printer(session, printer, ordered_jobs, config: SchedulerConfig) -> BuildProposal | None:
    """Build a single proposal for an idle printer from its ordered bucket."""
    if not ordered_jobs:
        return None
    batching_on = config.batching.get(printer.process, False)
    jobs = _select_batch(ordered_jobs, printer, config) if batching_on else [ordered_jobs[0]]

    material_spec = jobs[0].ticket.material_pref
    used = sum((_footprint(j) or 0.0) for j in jobs)
    fill_pct = round(used / _plate_area(printer), 4) if _plate_area(printer) else 0.0
    needs_swap = capability_match(jobs[0], printer, config).needs_swap
    annotation = annotate_material(session, material_spec, jobs, config)

    if batching_on:
        reason = (f"batched {len(jobs)} {printer.process.value} job(s) sharing {material_spec or 'material'} "
                  f"({fill_pct * 100:.0f}% of plate, cap {config.fill_pct_cap * 100:.0f}%)")
    else:
        reason = f"next up: {jobs[0].ticket.title} (batching off → one job per build)"

    return BuildProposal(
        printer_id=printer.id, printer_name=printer.name, process=printer.process.value,
        material_spec=material_spec, job_ids=[j.id for j in jobs], parts=len(jobs),
        fill_pct=fill_pct, fill_cap_pct=config.fill_pct_cap, needs_swap=needs_swap,
        material=annotation, reason=reason,
    )
