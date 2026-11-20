"""Test setup: a real PostgreSQL database, migrated and seeded once.

Each test runs inside a transaction that is rolled back afterwards, so tests
can create, change and delete freely without affecting each other. The API's
own transactions become savepoints inside it.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from invoice_api import seed
from invoice_api.auth import issue_token
from invoice_api.db import get_session
from invoice_api.main import app
from invoice_api.schemas import Role

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/invoice_api_test",
)


def ensure_database(url: str) -> None:
    """Create the database if it doesn't exist yet."""
    target = make_url(url)
    server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    server.dispose()


def migrate(connection: Connection, revision: str = "head") -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def downgrade(connection: Connection, revision: str) -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


def reset_schema(connection: Connection) -> None:
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    ensure_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        reset_schema(connection)
        migrate(connection)
        seed.load(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back when the test ends."""
    with engine.connect() as connection:
        outer = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def headers(role: Role) -> dict[str, str]:
    return {"X-SESSION": issue_token(role).token}


@pytest.fixture
def accountant() -> dict[str, str]:
    return headers(Role.ACCOUNTANT)


@pytest.fixture
def viewer() -> dict[str, str]:
    return headers(Role.VIEWER)
