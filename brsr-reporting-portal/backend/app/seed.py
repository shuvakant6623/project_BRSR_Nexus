"""Deterministic seed: entity hierarchy, users with scopes, framework versions,
reporting periods, metrics, assignments and demo data.

Run:  python -m app.seed

Seeding is idempotent: existing rows are matched by natural keys and skipped.
Demo anomalies are added in later-phase sections of this module as those
subsystems come online.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db.session import SessionLocal
from app.models import AppUser, Entity, UserEntityScope
from app.models.enums import EntityType, UserRole

logger = logging.getLogger(__name__)

# Demo credentials — development/demo only, change before any real deployment.
DEMO_PASSWORD = "Demo@12345"

USERS: list[dict] = [
    {"email": "admin@example.local", "full_name": "System Admin", "role": UserRole.ADMIN,
     "scope_names": ["MEIL Group"]},
    {"email": "manager@example.local", "full_name": "ESG Manager", "role": UserRole.ESG_MANAGER,
     "scope_names": ["MEIL Group"]},
    {"email": "reviewer@example.local", "full_name": "Lead Reviewer", "role": UserRole.REVIEWER,
     "scope_names": ["Subsidiary A", "Subsidiary B"]},
    {"email": "management@example.local", "full_name": "Management User", "role": UserRole.MANAGEMENT,
     "scope_names": ["MEIL Group"]},
    {"email": "assessor@example.local", "full_name": "External Assessor", "role": UserRole.ASSESSOR,
     "scope_names": ["MEIL Group"]},
]

ENTITIES: list[dict] = [
    # name, type, parent
    {"name": "MEIL Group", "type": EntityType.GROUP, "parent": None},
    {"name": "Subsidiary A", "type": EntityType.SUBSIDIARY, "parent": "MEIL Group"},
    {"name": "Subsidiary B", "type": EntityType.SUBSIDIARY, "parent": "MEIL Group"},
    {"name": "Business Unit A1", "type": EntityType.BUSINESS_UNIT, "parent": "Subsidiary A"},
    {"name": "Business Unit A2", "type": EntityType.BUSINESS_UNIT, "parent": "Subsidiary A"},
    {"name": "Business Unit B1", "type": EntityType.BUSINESS_UNIT, "parent": "Subsidiary B"},
    {"name": "Business Unit B2", "type": EntityType.BUSINESS_UNIT, "parent": "Subsidiary B"},
    {"name": "Plant Alpha", "type": EntityType.PLANT, "parent": "Business Unit A1"},
    {"name": "Plant Beta", "type": EntityType.PLANT, "parent": "Business Unit A1"},
    {"name": "Plant Gamma", "type": EntityType.PLANT, "parent": "Business Unit A2"},
    {"name": "Plant Delta", "type": EntityType.PLANT, "parent": "Business Unit A2"},
    {"name": "Project C", "type": EntityType.PROJECT, "parent": "Business Unit B1"},
    {"name": "Project D", "type": EntityType.PROJECT, "parent": "Business Unit B1"},
    {"name": "Plant Epsilon", "type": EntityType.PLANT, "parent": "Business Unit B2"},
    {"name": "Plant Zeta", "type": EntityType.PLANT, "parent": "Business Unit B2"},
]

DATA_OWNERS: list[dict] = [
    {"email": "owner-alpha@example.local", "full_name": "Owner — Plant Alpha", "plant": "Plant Alpha"},
    {"email": "owner-beta@example.local", "full_name": "Owner — Plant Beta", "plant": "Plant Beta"},
    {"email": "owner-gamma@example.local", "full_name": "Owner — Plant Gamma", "plant": "Plant Gamma"},
    {"email": "owner-delta@example.local", "full_name": "Owner — Plant Delta", "plant": "Plant Delta"},
    {"email": "owner-projc@example.local", "full_name": "Owner — Project C", "plant": "Project C"},
    {"email": "owner-eps@example.local", "full_name": "Owner — Plant Epsilon", "plant": "Plant Epsilon"},
]


def _get_or_create_entity(db: Session, name: str, entity_type: EntityType, parent: Entity | None) -> Entity:
    entity = db.scalar(select(Entity).where(Entity.name == name))
    if entity is None:
        entity = Entity(
            name=name, entity_type=entity_type,
            parent_id=parent.id if parent else None, effective_from="2020-04-01",
        )
        db.add(entity)
        db.flush()
        logger.info("seeded entity %s", name)
    return entity


def seed(db: Session) -> None:
    entities: dict[str, Entity] = {}
    for spec in ENTITIES:
        parent = entities.get(spec["parent"]) if spec["parent"] else None
        entities[spec["name"]] = _get_or_create_entity(db, spec["name"], spec["type"], parent)

    for spec in USERS:
        user = db.scalar(select(AppUser).where(AppUser.email == spec["email"]))
        if user is None:
            user = AppUser(
                email=spec["email"], full_name=spec["full_name"],
                hashed_password=hash_password(DEMO_PASSWORD), role=spec["role"],
            )
            db.add(user)
            db.flush()
            logger.info("seeded user %s", spec["email"])
        for scope_name in spec["scope_names"]:
            entity = entities[scope_name]
            exists = db.scalar(
                select(UserEntityScope).where(
                    UserEntityScope.user_id == user.id, UserEntityScope.entity_id == entity.id
                )
            )
            if exists is None:
                db.add(UserEntityScope(user_id=user.id, entity_id=entity.id))

    for spec in DATA_OWNERS:
        user = db.scalar(select(AppUser).where(AppUser.email == spec["email"]))
        if user is None:
            user = AppUser(
                email=spec["email"], full_name=spec["full_name"],
                hashed_password=hash_password(DEMO_PASSWORD), role=UserRole.DATA_OWNER,
            )
            db.add(user)
            db.flush()
            logger.info("seeded data owner %s", spec["email"])
        plant = entities[spec["plant"]]
        exists = db.scalar(
            select(UserEntityScope).where(
                UserEntityScope.user_id == user.id, UserEntityScope.entity_id == plant.id
            )
        )
        if exists is None:
            db.add(UserEntityScope(user_id=user.id, entity_id=plant.id))

    db.commit()
    logger.info("seed complete: %d entities, %d users", len(entities), len(db.scalars(select(AppUser)).all()))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    main()
