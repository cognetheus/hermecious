"""Migration harness against real, per-test scratch databases on the test server."""

from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy.engine import URL

from app.core.settings import Settings
from tests.integration.db import alembic, plain, scratch_database

HEAD = "0002"


@pytest.fixture
def scratch_database_url(settings: Settings) -> Iterator[URL]:
    with scratch_database(str(settings.database_url)) as url:
        yield url


def current_revision(database_url: URL) -> list[str]:
    with psycopg.connect(plain(database_url)) as conn:
        exists = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()
        if not exists or not exists[0]:
            return []
        return [row[0] for row in conn.execute("SELECT version_num FROM alembic_version")]


def test_upgrade_head_is_repeatable(scratch_database_url: URL) -> None:
    first = alembic("upgrade", "head", database_url=scratch_database_url)
    assert first.returncode == 0, first.stderr
    assert current_revision(scratch_database_url) == [HEAD]

    second = alembic("upgrade", "head", database_url=scratch_database_url)
    assert second.returncode == 0, second.stderr
    assert current_revision(scratch_database_url) == [HEAD]


def test_downgrade_to_base_and_back(scratch_database_url: URL) -> None:
    up = alembic("upgrade", "head", database_url=scratch_database_url)
    assert up.returncode == 0, up.stderr
    down = alembic("downgrade", "base", database_url=scratch_database_url)
    assert down.returncode == 0, down.stderr
    assert current_revision(scratch_database_url) == []
    again = alembic("upgrade", "head", database_url=scratch_database_url)
    assert again.returncode == 0, again.stderr
    assert current_revision(scratch_database_url) == [HEAD]


@pytest.mark.parametrize(
    "bad_url",
    ["", "not-a-url", "mysql://user:pw-secret-value@db/app_test"],
    ids=["empty", "malformed", "wrong-scheme"],
)
def test_invalid_database_url_refuses_to_migrate(bad_url: str) -> None:
    result = alembic("upgrade", "head", database_url=bad_url)
    assert result.returncode != 0
    assert "refusing to run: missing or invalid settings: DATABASE_URL" in result.stderr
    assert "pw-secret-value" not in result.stderr + result.stdout


def test_unreachable_database_fails_without_fallback() -> None:
    # Valid URL, nothing listening: the migration must fail, not pick another database.
    result = alembic("upgrade", "head", database_url="postgresql://user:pw@127.0.0.1:1/nowhere_test")
    assert result.returncode != 0
    assert "OperationalError" in result.stderr


def test_models_match_migrations(scratch_database_url: URL) -> None:
    """Drift guard: the ORM metadata and the migrated schema describe the same tables."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.persistence.base import Base, sqlalchemy_url
    from app.persistence.registry import register_models

    assert alembic("upgrade", "head", database_url=scratch_database_url).returncode == 0
    register_models()
    engine = create_engine(sqlalchemy_url(plain(scratch_database_url)))
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []
