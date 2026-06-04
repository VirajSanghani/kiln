"""Capability buckets — §3. A Job runs only where it physically can.

The queue is partitioned by capability MATCH, not just process:
  - process match (an SLA job can't run on an FDM printer),
  - material capability (PA12-CF only on an enclosed printer; TPU only on direct-drive),
  - build-volume fit (part bbox ≤ printer build volume),
  - loaded-material match OR an explicit "swap acceptable" flag.
A Job appears in EVERY bucket it can run in (it may be eligible for several).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import MATERIAL_REQUIREMENTS, SchedulerConfig


@dataclass
class Match:
    ok: bool
    needs_swap: bool = False
    reasons: list[str] = field(default_factory=list)   # why NOT ok / notes


def _part_file_version(job):
    # the version that will print: the Job's pinned version, else the ticket's current one
    return job.file_version or job.ticket.current_file_version


def _bbox(fv):
    if fv is None or fv.bbox_x is None or fv.bbox_y is None or fv.bbox_z is None:
        return None
    return (fv.bbox_x, fv.bbox_y, fv.bbox_z)


def _fits_volume(job, printer) -> tuple[bool, str | None]:
    bbox = _bbox(_part_file_version(job))
    if bbox is None:
        return True, "bbox unknown — assumed to fit"   # informs, never blocks on missing data
    part = sorted(bbox)
    vol = sorted([printer.build_volume_x, printer.build_volume_y, printer.build_volume_z])
    if all(p <= v for p, v in zip(part, vol)):
        return True, None
    return False, f"part {bbox} exceeds build volume {(printer.build_volume_x, printer.build_volume_y, printer.build_volume_z)}"


def capability_match(job, printer, config: SchedulerConfig) -> Match:
    reasons: list[str] = []
    desired_material = job.ticket.material_pref

    # 1) process
    if job.ticket.target_process != printer.process:
        return Match(ok=False, reasons=[f"process {job.ticket.target_process.value} != {printer.process.value}"])

    # 2) material capability
    caps = printer.capabilities or {}
    allowed_materials = caps.get("materials")
    if desired_material and allowed_materials and desired_material not in allowed_materials:
        reasons.append(f"printer can't run {desired_material} (allowed: {allowed_materials})")
    if desired_material in MATERIAL_REQUIREMENTS:
        for cap, required in MATERIAL_REQUIREMENTS[desired_material].items():
            if caps.get(cap) != required:
                reasons.append(f"{desired_material} needs {cap}={required}")

    # 3) build-volume fit
    fits, fit_note = _fits_volume(job, printer)
    if not fits:
        reasons.append(fit_note)

    # 4) loaded-material match OR swap-acceptable
    loaded = printer.loaded_material.spec if printer.loaded_material else None
    needs_swap = bool(desired_material) and loaded != desired_material
    if needs_swap and not config.allow_swaps:
        reasons.append(f"loaded {loaded}, needs {desired_material} (swaps off)")

    return Match(ok=not reasons, needs_swap=needs_swap, reasons=reasons)


def eligible_jobs(jobs, printer, config: SchedulerConfig) -> list:
    """Jobs that can physically run on this printer."""
    return [j for j in jobs if capability_match(j, printer, config).ok]
