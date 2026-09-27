"""Shared pytest fixtures.

Integration tests run against the real PostgreSQL service from docker compose,
in a dedicated brsr_test database that is migrated once per session.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

TEST_DB = "brsr_test"

ADMIN_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://brsr:brsr@postgres:5432/brsr"
)


def _admin_engine():
    return create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def test_db_url():
    admin = _admin_engine()
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()
    return ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"


@pytest.fixture(scope="session")
def migrated_engine(test_db_url):
    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = test_db_url
    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(test_db_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(migrated_engine):
    """A transaction-wrapped session: rolled back after each test."""
    connection = migrated_engine.connect()
    tx = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    tx.rollback()
    connection.close()


@pytest.fixture()
def unique_code() -> str:
    return uuid.uuid4().hex[:12]
