"""Entity-hierarchy domain service (adjacency list + recursive CTE)."""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

SUBTREE_SQL = text(
    """
    WITH RECURSIVE subtree AS (
        SELECT id FROM entity WHERE id = :root
        UNION ALL
        SELECT e.id FROM entity e JOIN subtree s ON e.parent_id = s.id
    )
    SELECT id FROM subtree
    """
)


def get_descendant_ids(session: Session, entity_id: uuid.UUID, include_self: bool = True) -> set[uuid.UUID]:
    rows = session.execute(SUBTREE_SQL, {"root": str(entity_id)}).scalars().all()
    ids = {uuid.UUID(str(r)) for r in rows}
    if not include_self:
        ids.discard(entity_id)
    return ids


def get_user_scoped_entity_ids(session: Session, user) -> set[uuid.UUID]:
    """Union of every allowed subtree for the user's entity scopes."""
    scoped: set[uuid.UUID] = set()
    for scope in user.entity_scopes:
        scoped |= get_descendant_ids(session, scope.entity_id)
    return scoped


def get_ancestor_chain(session: Session, entity_id: uuid.UUID) -> list[uuid.UUID]:
    """Chain from root to the entity itself (for breadcrumbs)."""
    result: list[uuid.UUID] = []
    current: uuid.UUID | None = entity_id
    seen: set[uuid.UUID] = set()
    while current is not None and current not in seen:
        seen.add(current)
        row = session.execute(
            text("SELECT parent_id FROM entity WHERE id = :i"), {"i": str(current)}
        ).scalar()
        result.append(current)
        current = row
    result.reverse()
    return result
