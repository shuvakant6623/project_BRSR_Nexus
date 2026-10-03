"""add ANOMALY_DETECTION validation rule class

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on PG < 12
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE validation_rule_class ADD VALUE IF NOT EXISTS 'ANOMALY_DETECTION'"
    )


def downgrade() -> None:
    # enum value removal is not supported by PostgreSQL; leave in place
    pass
