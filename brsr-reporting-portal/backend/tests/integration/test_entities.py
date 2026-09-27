"""Organization-engine integration tests: hierarchy invariants and scoped reads."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import DEMO_PASSWORD, seed

TEST_STATE: dict = {}


@pytest.fixture(scope="module")
def client(migrated_engine):
    from sqlalchemy.orm import sessionmaker

    from app.db.session import get_db

    TEST_STATE["engine"] = migrated_engine
    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seeded(migrated_engine):
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=migrated_engine, autoflush=False, expire_on_commit=False)
    with TestSession() as db:
        seed(db)


def _login(client, email, password=DEMO_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _token(client, email):
    return {"Authorization": f"Bearer {_login(client, email).json()['access_token']}"}


def _find_by_name(client, headers, name):
    entities = client.get("/api/v1/entities", headers=headers).json()
    return next(e for e in entities if e["name"] == name)


def test_admin_lists_all_entities_owner_lists_own_subtree(client, seeded):
    admin = client.get("/api/v1/entities", headers=_token(client, "admin@example.local")).json()
    # 15 seeded entities; earlier suite runs may have created extra test entities
    assert len(admin) >= 15
    owner = client.get(
        "/api/v1/entities", headers=_token(client, "owner-alpha@example.local")
    ).json()
    assert [e["name"] for e in owner] == ["Plant Alpha"]


def test_owner_cannot_read_foreign_entity(client, seeded):
    admin_headers = _token(client, "admin@example.local")
    plant_beta = _find_by_name(client, admin_headers, "Plant Beta")
    r = client.get(
        f"/api/v1/entities/{plant_beta['id']}",
        headers=_token(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 403


def test_owner_can_read_own_entity(client, seeded):
    admin_headers = _token(client, "admin@example.local")
    plant_alpha = _find_by_name(client, admin_headers, "Plant Alpha")
    r = client.get(
        f"/api/v1/entities/{plant_alpha['id']}",
        headers=_token(client, "owner-alpha@example.local"),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Plant Alpha"


def test_admin_creates_entity_and_audits(client, seeded):
    headers = _token(client, "admin@example.local")
    bu = _find_by_name(client, headers, "Business Unit B2")
    r = client.post(
        "/api/v1/entities",
        json={
            "name": f"Plant Test {uuid.uuid4().hex[:6]}",
            "entity_type": "PLANT",
            "parent_id": bu["id"],
            "effective_from": "2025-04-01",
        },
        headers=headers,
    )
    assert r.status_code == 201
    entity_id = r.json()["id"]
    from sqlalchemy import text

    with TEST_STATE["engine"].connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM audit_event WHERE object_type='entity' AND object_id=:i"),
            {"i": entity_id},
        ).scalar()
    assert count >= 1


def test_non_admin_cannot_create_entity(client, seeded):
    r = client.post(
        "/api/v1/entities",
        json={"name": "Nope", "entity_type": "PLANT", "effective_from": "2025-04-01"},
        headers=_token(client, "manager@example.local"),
    )
    assert r.status_code == 403


def test_entity_cannot_be_its_own_parent(client, seeded):
    headers = _token(client, "admin@example.local")
    bu = _find_by_name(client, headers, "Business Unit B2")
    r = client.patch(
        f"/api/v1/entities/{bu['id']}",
        json={"parent_id": bu["id"]},
        headers=headers,
    )
    assert r.status_code == 422


def test_cycle_prevention_move_under_descendant(client, seeded):
    headers = _token(client, "admin@example.local")
    sub_a = _find_by_name(client, headers, "Subsidiary A")
    plant_alpha = _find_by_name(client, headers, "Plant Alpha")
    # move Subsidiary A under Plant Alpha (its own descendant) -> must fail
    r = client.patch(
        f"/api/v1/entities/{sub_a['id']}",
        json={"parent_id": plant_alpha["id"]},
        headers=headers,
    )
    assert r.status_code == 422
    # hierarchy unchanged
    after = client.get(f"/api/v1/entities/{sub_a['id']}", headers=headers).json()
    assert after["parent_id"] != plant_alpha["id"]


def test_effective_dates_validation(client, seeded):
    headers = _token(client, "admin@example.local")
    r = client.post(
        "/api/v1/entities",
        json={
            "name": "Bad Dates",
            "entity_type": "PLANT",
            "effective_from": "2025-04-01",
            "effective_to": "2024-04-01",
        },
        headers=headers,
    )
    assert r.status_code == 422


def test_soft_deactivation_preserves_entity(client, seeded):
    headers = _token(client, "admin@example.local")
    name = f"Deprecate {uuid.uuid4().hex[:6]}"
    bu = _find_by_name(client, headers, "Business Unit A1")
    created = client.post(
        "/api/v1/entities",
        json={"name": name, "entity_type": "PLANT", "parent_id": bu["id"], "effective_from": "2025-04-01"},
        headers=headers,
    ).json()
    patched = client.patch(
        f"/api/v1/entities/{created['id']}", json={"is_active": False}, headers=headers
    ).json()
    assert patched["is_active"] is False
    # still retrievable (soft deactivation, never deleted)
    fetched = client.get(f"/api/v1/entities/{created['id']}", headers=headers).json()
    assert fetched["id"] == created["id"]
    # hidden from default list, visible with include_inactive
    names = [e["name"] for e in client.get("/api/v1/entities", headers=headers).json()]
    assert name not in names
    names_all = [
        e["name"]
        for e in client.get("/api/v1/entities?include_inactive=true", headers=headers).json()
    ]
    assert name in names_all


def test_create_entity_with_unknown_parent_422(client, seeded):
    r = client.post(
        "/api/v1/entities",
        json={
            "name": "Orphan",
            "entity_type": "PLANT",
            "parent_id": str(uuid.uuid4()),
            "effective_from": "2025-04-01",
        },
        headers=_token(client, "admin@example.local"),
    )
    assert r.status_code == 422


def test_admin_grants_entity_scope(client, seeded):
    headers = _token(client, "admin@example.local")
    users = client.get("/api/v1/users", headers=headers).json()
    owner = next(u for u in users if u["email"] == "owner-beta@example.local")
    gamma = _find_by_name(client, headers, "Plant Gamma")
    r = client.post(
        f"/api/v1/users/{owner['id']}/scopes",
        json={"entity_id": gamma["id"]},
        headers=headers,
    )
    # 201 on first run; 409 when the grant already exists from a previous run
    assert r.status_code in (201, 409)
    # duplicate grant rejected
    r = client.post(
        f"/api/v1/users/{owner['id']}/scopes",
        json={"entity_id": gamma["id"]},
        headers=headers,
    )
    assert r.status_code == 409
    # owner-beta now sees both subtrees
    owner_entities = client.get(
        "/api/v1/entities", headers=_token(client, "owner-beta@example.local")
    ).json()
    names = {e["name"] for e in owner_entities}
    assert names == {"Plant Beta", "Plant Gamma"}
