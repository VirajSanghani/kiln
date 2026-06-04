"""Slicer-summary parser.

PARSE only — we never slice in-app (scope fence). Handles the gcode summary comments of
PrusaSlicer, Cura, and Bambu Studio, plus a structured manual-paste fallback. Output is
always labeled "slicer est." in the UI and is ~10–20% off; never implied as measured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class SlicerParseError(ValueError):
    pass


@dataclass
class ParsedEstimate:
    slicer_name: str
    est_time_seconds: int | None
    est_material_qty: float | None
    est_material_unit: str | None


def _hms_to_seconds(text: str) -> int | None:
    """'1h 48m 30s' / '48m 30s' / '90s' -> seconds."""
    total = 0
    found = False
    for value, unit in re.findall(r"(\d+)\s*([hms])", text):
        found = True
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total if found else None


def _search(pattern: str, text: str):
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parse_prusaslicer(text: str) -> ParsedEstimate:
    t = _search(r"estimated printing time \(normal mode\)\s*=\s*(.+)", text)
    g = _search(r"filament used \[g\]\s*=\s*([\d.]+)", text)
    return ParsedEstimate("PrusaSlicer", _hms_to_seconds(t) if t else None,
                          float(g) if g else None, "g" if g else None)


def _parse_bambu(text: str) -> ParsedEstimate:
    t = _search(r"model printing time:\s*([0-9hms ]+)", text)
    g = _search(r"total filament weight \[g\]\s*:?\s*([\d.]+)", text)
    return ParsedEstimate("Bambu Studio", _hms_to_seconds(t) if t else None,
                          float(g) if g else None, "g" if g else None)


def _parse_cura(text: str) -> ParsedEstimate:
    secs = _search(r";TIME:\s*(\d+)", text)
    # Cura reports filament as length (metres); recorded as-is with unit 'm' (no density
    # in the summary to convert to grams — a documented limitation).
    length = _search(r";Filament used:\s*([\d.]+)\s*m", text)
    return ParsedEstimate("Cura", int(secs) if secs else None,
                          float(length) if length else None, "m" if length else None)


def _parse_manual(text: str) -> ParsedEstimate:
    """Structured key:value fallback, e.g.
        time: 1h 48m
        material: 22 g
    """
    t = _search(r"time\s*[:=]\s*(.+)", text)
    mat = _search(r"material\s*[:=]\s*([\d.]+)\s*([a-zA-Z]+)", text)
    qty = unit = None
    if mat:
        m = re.search(r"material\s*[:=]\s*([\d.]+)\s*([a-zA-Z]+)", text, re.IGNORECASE)
        qty, unit = float(m.group(1)), m.group(2)
    seconds = None
    if t:
        seconds = _hms_to_seconds(t) or (int(t) if t.strip().isdigit() else None)
    if seconds is None and qty is None:
        raise SlicerParseError("manual paste must include a 'time:' and/or 'material:' line")
    return ParsedEstimate("manual", seconds, qty, unit)


def parse(text: str) -> ParsedEstimate:
    """Detect the source from its signature and parse. Raises SlicerParseError if unknown."""
    low = text.lower()
    if "prusaslicer" in low or "filament used [g]" in low or "estimated printing time (normal mode)" in low:
        return _parse_prusaslicer(text)
    if "bambu" in low or "total filament weight" in low or "model printing time" in low:
        return _parse_bambu(text)
    if ";time:" in low or "cura" in low or ";filament used:" in low:
        return _parse_cura(text)
    if re.search(r"\b(time|material)\s*[:=]", low):
        return _parse_manual(text)
    raise SlicerParseError("could not recognise the slicer summary format")
