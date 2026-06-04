"""KILN scheduler — explicit, legible POLICY (see SCHEDULER_DESIGN.md).

The scheduler PROPOSES; a human CONFIRMS. It is a read-only computation over the current
DB state that produces (1) an ordered next-up queue per capability bucket and (2) Build
proposals for idle printers. It never mutates state and never auto-starts a machine —
`confirm_proposal` is the ONLY mutating entry point and runs solely on operator action.
"""
from .config import (  # noqa: F401
    DEFAULT_BATCHING,
    MATERIAL_REQUIREMENTS,
    Bucket,
    BuildProposal,
    MaterialAnnotation,
    RankedJob,
    SchedulerConfig,
    SchedulerView,
)
from .service import build_schedule, confirm_proposal  # noqa: F401
