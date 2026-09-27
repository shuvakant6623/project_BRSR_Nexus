"""Entity-hierarchy domain service (adjacency list + recursive CTE)."""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Entity

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


class EntityValidationError(Exception):
    pass


def validate_hierarchy_invariants(
    session: Session,
    entity_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
) -> None:
    """Reject self-parenting and cycles before any parent change is persisted."""
    if parent_id is None:
        return
    if entity_id is not None and parent_id == entity_id:
        raise EntityValidationError("An entity cannot be its own parent")
    if entity_id is not None and parent_id in get_descendant_ids(session, entity_id, include_self=True):
        raise EntityValidationError("Cannot move an entity under its own descendant (cycle)")


def create_entity(
    session: Session,
    *,
    name: str,
    entity_type,
    parent_id: uuid.UUID | None,
    effective_from,
    effective_to=None,
    reporting_boundary_notes: str | None = None,
) -> Entity:
    if parent_id is not None:
        parent = session.get(Entity, parent_id)
        if parent is None:
            raise EntityValidationError(f"Parent entity {parent_id} does not exist")
    validate_hierarchy_invariants(session, None, parent_id)
    if effective_to is not None and effective_to < effective_from:
        raise EntityValidationError("effective_to must be on or after effective_from")
    entity = Entity(
        name=name,
        entity_type=entity_type,
        parent_id=parent_id,
        effective_from=effective_from,
        effective_to=effective_to,
        reporting_boundary_notes=reporting_boundary_notes,
    )
    session.add(entity)
    session.flush()
    return entity


def update_entity(session: Session, entity: Entity, changes: dict) -> Entity:
    if "parent_id" in changes and changes["parent_id"] != entity.parent_id:
        validate_hierarchy_invariants(session, entity.id, changes["parent_id"])
    for field, value in changes.items():
        setattr(entity, field, value)
    if entity.effective_to is not None and entity.effective_to < entity.effective_from:
        raise EntityValidationError("effective_to must be on or after effective_from")
    session.flush()
    return entity
