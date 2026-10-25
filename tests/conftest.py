"""Fixtures shared by the API tests.

Each test gets a migrated database with all business tables emptied, two
users (admin and staff), and a new in-process client. Tests do not depend
on each other or on seed data from `scripts/seed.py`.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password
from tests.support import ADMIN_EMAIL, PASSWORD, STAFF_EMAIL

TEST_DATABASE_URL = os.environ.get(
    "ORDERFLOW_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres@127.0.0.1:5432/orderflow_test",
)

_TABLES = (
    "inventory_movements",
    "order_items",
    "orders",
    "products",
    "customers",
    "users",
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        jwt_secret="test-secret-key-at-least-32-characters",
        bcrypt_rounds=4,
        access_token_minutes=30,
        log_level="WARNING",
    )


def _migrate(url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def settings() -> Settings:
    configured = _settings()
    try:
        _migrate(configured.database_url)
    except OperationalError as exc:
        raise RuntimeError(
            "Cannot reach the test database. Start PostgreSQL and create "
            f"the database in {TEST_DATABASE_URL}."
        ) from exc
    return configured


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    application = create_app(settings)
    with application.state.engine.begin() as connection:
        connection.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
        )
    session = application.state.session_factory()
    try:
        for email, role in ((ADMIN_EMAIL, "admin"), (STAFF_EMAIL, "staff")):
            session.add(
                User(
                    email=email,
                    password_hash=hash_password(PASSWORD, settings.bcrypt_rounds),
                    role=role,
                    is_active=True,
                )
            )
        session.commit()
    finally:
        session.close()

    with TestClient(application) as test_client:
        yield test_client
    application.state.engine.dispose()
