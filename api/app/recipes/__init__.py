"""Process recipes as DATA (not code branches).

Adding a process = adding an entry to RECIPES — never editing an engine. The transition
engine that *consumes* this data lands in Phase 2; Phase 1 only needs the data itself
(for stage validity, the timeline order, active/passive typing, and status derivation).
"""
from .registry import (  # noqa: F401
    DONE,
    RECIPES,
    SIDE_STATES,
    StageDef,
    StageType,
    entry_stage,
    is_active,
    is_terminal_stage,
    occupies_machine,
    recipe_for,
    stage_def,
    stage_index,
    stage_names,
)
