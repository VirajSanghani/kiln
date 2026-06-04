"""The recipe registry.

A recipe is an ORDERED LIST of stage defs, each = {name, label, type(active|passive),
allowed_next[]} (resolution #2). The list order is the display/timeline spine; the
allowed_next edges are what the Phase 2 engine validates against.

Conventions (resolution #1/#2):
- R1: a recipe spans **Printing → Done**. The pre-Build spine (submitted/queued/
  scheduled) is NOT in the recipe.
- R2: the **terminal** stage is the one whose `allowed_next` is empty (here: `done`).
- Entry stage = the first element of the list.
- Side-states (on_hold/failed/cancelled) are UNIVERSAL — reachable from any stage — and
  deliberately NOT part of any `allowed_next`.
- `type` (active|passive) is consumed by the timeline UI and the Phase 6 utilization
  metric (active = machine/operator busy; passive = elapsing/waiting).
"""
from dataclasses import dataclass

from ..enums import ProcessType

DONE = "done"

# Universal side-states (NOT recipe stages, NOT in allowed_next).
SIDE_STATES = ("on_hold", "failed", "cancelled")


class StageType:
    active = "active"
    passive = "passive"


@dataclass(frozen=True)
class StageDef:
    name: str
    label: str
    type: str  # StageType.active | StageType.passive
    allowed_next: tuple[str, ...]
    # Does this stage tie up the PRINTER itself? On-machine stages (printing, SLS/MJF
    # cooldown, SLA wash/cure) keep the printer unavailable for a new Build; off-machine
    # bench stages (FDM support removal, QC) free the printer. Feeds the scheduler's
    # availability check (Phase 4 resolution of the Phase 3 open question).
    occupies_machine: bool = False


A = StageType.active
P = StageType.passive

RECIPES: dict[ProcessType, tuple[StageDef, ...]] = {
    ProcessType.FDM: (
        StageDef("printing", "Printing", A, ("support_removal",), occupies_machine=True),
        StageDef("support_removal", "Support removal", A, ("qc",)),   # off-machine bench work
        StageDef("qc", "QC", A, ("done",)),
        StageDef("done", "Done", P, ()),
    ),
    ProcessType.SLA: (
        StageDef("printing", "Printing", A, ("drain",), occupies_machine=True),
        StageDef("drain", "Drain", P, ("wash",)),          # passive: excess resin drips off
        StageDef("wash", "Wash", A, ("cure",), occupies_machine=True),   # on-machine station
        StageDef("cure", "Cure", A, ("qc",), occupies_machine=True),     # on-machine cure
        StageDef("qc", "QC", A, ("done",)),
        StageDef("done", "Done", P, ()),
    ),
    ProcessType.SLS: (
        StageDef("printing", "Printing", A, ("cooldown",), occupies_machine=True),
        StageDef("cooldown", "Cooldown", P, ("depowder",), occupies_machine=True),  # part still in chamber
        StageDef("depowder", "Depowder", A, ("qc",)),                    # off-machine station
        StageDef("qc", "QC", A, ("done",)),
        StageDef("done", "Done", P, ()),
    ),
    ProcessType.MJF: (
        StageDef("printing", "Printing", A, ("cooldown",), occupies_machine=True),
        StageDef("cooldown", "Cooldown", P, ("depowder",), occupies_machine=True),
        # Optional Dye: depowder may go to dye OR skip straight to qc — a real branch,
        # which is exactly why allowed_next is a list, not a single successor.
        StageDef("depowder", "Depowder", A, ("dye", "qc")),
        StageDef("dye", "Dye", A, ("qc",)),
        StageDef("qc", "QC", A, ("done",)),
        StageDef("done", "Done", P, ()),
    ),
}


def recipe_for(process: ProcessType) -> tuple[StageDef, ...]:
    return RECIPES[process]


def stage_names(process: ProcessType) -> tuple[str, ...]:
    return tuple(s.name for s in recipe_for(process))


def stage_def(process: ProcessType, name: str) -> StageDef:
    for s in recipe_for(process):
        if s.name == name:
            return s
    raise KeyError(f"{name!r} is not a stage of the {process.value} recipe")


def entry_stage(process: ProcessType) -> str:
    return recipe_for(process)[0].name


def stage_index(process: ProcessType, name: str) -> int:
    return stage_names(process).index(name)


def is_terminal_stage(process: ProcessType, name: str) -> bool:
    """R2: terminal == empty allowed_next."""
    return len(stage_def(process, name).allowed_next) == 0


def is_active(process: ProcessType, name: str) -> bool:
    return stage_def(process, name).type == StageType.active


def occupies_machine(process: ProcessType, name: str) -> bool:
    return stage_def(process, name).occupies_machine
