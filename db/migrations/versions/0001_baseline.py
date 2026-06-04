"""baseline (empty)

Establishes the Alembic version chain so `alembic upgrade head` is a real, working
operation from Phase 0. Intentionally creates no tables — Phase 0 does no data
modeling. The full schema (Build/Job split, FileVersion chain, audit logs) lands in
Phase 1 as the next migration on top of this baseline.

Revision ID: 0001
Revises:
Create Date: 2026-06-04
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty — baseline marker only.
    pass


def downgrade() -> None:
    pass
