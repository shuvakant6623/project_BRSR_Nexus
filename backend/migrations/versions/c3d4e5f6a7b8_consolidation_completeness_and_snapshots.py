"""add consolidation completeness and metric override columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "consolidation_trace",
        sa.Column("is_complete", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "consolidation_trace",
        sa.Column(
            "missing_child_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "metric_value",
        sa.Column("is_override", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "metric_value",
        sa.Column("override_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("metric_value", "override_reason")
    op.drop_column("metric_value", "is_override")
    op.drop_column("consolidation_trace", "missing_child_ids")
    op.drop_column("consolidation_trace", "is_complete")
