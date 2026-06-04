"""Inventory warnings — the full set. INFORMS, NEVER BLOCKS.

Every warning here is a derived annotation computed from Material fields + thresholds; it
never prevents queuing or scheduling. Surfaced on the material shelf + ops dashboard.
"""
from __future__ import annotations

from datetime import date, timedelta

from .enums import DryingState, MaterialKind

# powder is considered "tired" below this fresh fraction
MIN_FRESH_RATIO = 0.30


def material_warnings(material, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []
    unit = material.unit or ""

    # low stock vs reorder threshold (R6: unset threshold never warns)
    if material.reorder_threshold is not None and material.qty_remaining < material.reorder_threshold:
        out.append({
            "kind": "low_stock", "severity": "warn",
            "message": f"low stock: {material.qty_remaining:g}{unit} < reorder {material.reorder_threshold:g}{unit}",
        })

    # resin shelf life
    if material.kind == MaterialKind.resin and material.opened_date and material.shelf_life_days:
        expiry = material.opened_date + timedelta(days=material.shelf_life_days)
        days_left = (expiry - today).days
        if days_left <= 0:
            out.append({"kind": "shelf_life", "severity": "critical",
                        "message": f"shelf life: EXPIRED {-days_left}d ago"})
        elif days_left <= 14:
            out.append({"kind": "shelf_life", "severity": "warn",
                        "message": f"shelf life: {days_left}d left"})
        elif days_left <= 30:
            out.append({"kind": "shelf_life", "severity": "info",
                        "message": f"shelf life: {days_left}d left"})

    # filament drying
    if material.kind == MaterialKind.filament and material.drying_state == DryingState.needs_drying:
        out.append({"kind": "drying", "severity": "warn", "message": "needs drying before use"})

    # powder refresh / virgin-used blend
    if material.kind == MaterialKind.powder and material.virgin_qty is not None and material.used_qty is not None:
        total = material.virgin_qty + material.used_qty
        ratio = (material.virgin_qty / total) if total else 0.0
        if ratio < MIN_FRESH_RATIO:
            out.append({"kind": "powder_refresh", "severity": "warn",
                        "message": f"refresh ratio low: {ratio * 100:.0f}% fresh (< {MIN_FRESH_RATIO * 100:.0f}%)"})
        else:
            out.append({"kind": "powder_refresh", "severity": "info",
                        "message": f"blend {ratio * 100:.0f}% fresh / {100 - ratio * 100:.0f}% used"})

    return out
