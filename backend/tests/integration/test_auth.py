"""Auth and RBAC integration tests against real PostgreSQL + Redis."""
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


def test_login_success_and_me(client, seeded):
    r = _login(client, "admin@example.local")
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["token_type"] == "bearer"
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "ADMIN"
    assert len(body["entity_scope_ids"]) >= 1


def test_login_wrong_password_401(client, seeded):
    r = _login(client, "admin@example.local", password="wrong-password")
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"}).status_code
        == 401
    )


def test_refresh_rotation_and_logout_revocation(client, seeded):
    tokens = _login(client, "owner-alpha@example.local").json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    # old refresh token must be rejected after rotation
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
    # logout revokes the new refresh token
    client.post("/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]})
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 401


def test_login_rate_limit(client):
    email = "ratelimit-test@example.local"
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    assert r.status_code == 429


def test_data_owner_scope_is_own_subtree_only(client, seeded):
    tokens = _login(client, "owner-alpha@example.local").json()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    scope = me.json()["entity_scope_ids"]
    # Plant Alpha subtree is exactly one entity (it has no children)
    assert len(scope) == 1


def test_owner_cannot_list_users(client, seeded):
    tokens = _login(client, "owner-alpha@example.local").json()
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 403


def test_management_cannot_create_user(client, seeded):
    tokens = _login(client, "management@example.local").json()
    r = client.post(
        "/api/v1/users",
        json={"email": "x@example.local", "full_name": "X", "password": "whatever123", "role": "MANAGEMENT"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 403


def test_admin_creates_user_with_audit_event(client, seeded):
    tokens = _login(client, "admin@example.local").json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    email = f"created-{uuid.uuid4().hex[:8]}@example.local"
    r = client.post(
        "/api/v1/users",
        json={"email": email, "full_name": "Created By Test", "password": "Temp@12345", "role": "MANAGEMENT"},
        headers=headers,
    )
    assert r.status_code == 201
    # duplicate email rejected
    r = client.post(
        "/api/v1/users",
        json={"email": email, "full_name": "Dup", "password": "Temp@12345", "role": "MANAGEMENT"},
        headers=headers,
    )
    assert r.status_code == 409
    # audit event recorded for the creation
    from sqlalchemy import (
        create_engine,  # noqa: F401
        text,
    )

    with TEST_STATE["engine"].connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM audit_event WHERE object_type='app_user' "
                "AND new_value->>'email' = :e"
            ),
            {"e": email},
        ).scalar()
    assert count >= 1


def test_validation_error_is_rfc7807(client):
    r = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": ""})
    assert r.status_code == 422
    body = r.json()
    assert body["type"] == "validation_error"
    assert body["status"] == 422
    assert isinstance(body["errors"], list) and body["errors"]
