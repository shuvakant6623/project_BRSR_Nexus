"""audit_event immutability trigger

Rejects any UPDATE or DELETE on audit_event at the database level.
Audit events are append-only by design; this is the database-side defense.

Revision ID: a1b2c3d4e5f6
Revises: fc6d8c4e4389
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fc6d8c4e4389"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event rows are immutable (attempted %)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_immutable
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS audit_event_immutable ON audit_event;
DROP FUNCTION IF EXISTS prevent_audit_mutation();
"""


def upgrade() -> None:
    op.execute(TRIGGER_SQL)


def downgrade() -> None:
    op.execute(DROP_TRIGGER_SQL)
