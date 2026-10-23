"""Integration tests run only against a disposable test stack (scripts/test-integration.sh).

Fails closed: without HERMECIOUS_ENV=test and a database whose name ends in
`_test`, the whole session aborts instead of touching another database.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from redis import Redis
from sqlalchemy.engine import URL

from app.core.clock import FixedClock
from app.core.settings import Settings, SettingsError, load_settings
from app.main import close_app, create_app
from tests.factories import TEST_ORIGIN
from tests.integration.db import alembic, plain, scratch_database


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("HERMECIOUS_ENV") != "test":
        pytest.exit("integration tests require HERMECIOUS_ENV=test (use scripts/test-integration.sh)", returncode=2)
    try:
        settings = load_settings()
    except SettingsError as exc:
        pytest.exit(f"integration tests refused: {exc}", returncode=2)
    database = (settings.database_url.path or "").lstrip("/")
    if not database.endswith("_test"):
        pytest.exit("integration tests refused: DATABASE_URL must name a database ending in _test", returncode=2)


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    yield load_settings()


# Seeded by migrations, not by tests: never truncated.
REFERENCE_TABLES = frozenset({"alembic_version", "verticals"})


@pytest.fixture(scope="session")
def migrated_database(settings: Settings) -> Iterator[URL]:
    """One scratch database per session, migrated to head through the real Alembic CLI."""
    with scratch_database(str(settings.database_url), "app") as url:
        result = alembic("upgrade", "head", database_url=url)
        assert result.returncode == 0, result.stderr
        yield url


@pytest.fixture
def app_settings(settings: Settings, migrated_database: URL) -> Settings:
    return settings.model_copy(
        update={"database_url": PostgresDsn(plain(migrated_database)), "allowed_origins_raw": TEST_ORIGIN}
    )


@pytest.fixture
def clean_state(app_settings: Settings) -> None:
    """Empty every application table (keeping migration-seeded reference data) and the test Redis."""
    with psycopg.connect(str(app_settings.database_url), autocommit=True) as conn:
        tables = [
            row[0]
            for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            if row[0] not in REFERENCE_TABLES
        ]
        if tables:
            conn.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE")
    with Redis.from_url(str(app_settings.redis_url)) as redis_client:
        redis_client.flushdb()


@pytest.fixture
def app(app_settings: Settings, clock: FixedClock, clean_state: None) -> Iterator[FastAPI]:
    application = create_app(app_settings, clock=clock)
    yield application
    close_app(application)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)
