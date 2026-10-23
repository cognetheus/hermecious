"""Migration harness against real, per-test scratch databases on the test server."""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import URL, make_url

from app.core.settings import Settings

API_ROOT = Path(__file__).resolve().parents[2]


def plain(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def alembic(*args: str, database_url: URL | str) -> subprocess.CompletedProcess[str]:
    # URL objects repr with a masked password, so failure output never shows it.
    value = plain(database_url) if isinstance(database_url, URL) else database_url
    env = {**os.environ, "DATABASE_URL": value}
    return subprocess.run(  # noqa: S603  # fixed argv, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def scratch_database_url(settings: Settings) -> Iterator[URL]:
    """A brand-new empty database, dropped afterwards."""
    server_url = make_url(str(settings.database_url))
    name = f"hermecious_scratch_{uuid.uuid4().hex[:12]}_test"
    admin_dsn = plain(server_url.set(drivername="postgresql"))
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield server_url.set(database=name)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def current_revision(database_url: URL) -> list[str]:
    with psycopg.connect(plain(database_url)) as conn:
        exists = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()
        if not exists or not exists[0]:
            return []
        return [row[0] for row in conn.execute("SELECT version_num FROM alembic_version")]


def test_upgrade_head_is_repeatable(scratch_database_url: URL) -> None:
    first = alembic("upgrade", "head", database_url=scratch_database_url)
    assert first.returncode == 0, first.stderr
    assert current_revision(scratch_database_url) == ["0001"]

    second = alembic("upgrade", "head", database_url=scratch_database_url)
    assert second.returncode == 0, second.stderr
    assert current_revision(scratch_database_url) == ["0001"]


def test_downgrade_to_base_and_back(scratch_database_url: URL) -> None:
    up = alembic("upgrade", "head", database_url=scratch_database_url)
    assert up.returncode == 0, up.stderr
    down = alembic("downgrade", "base", database_url=scratch_database_url)
    assert down.returncode == 0, down.stderr
    assert current_revision(scratch_database_url) == []
    again = alembic("upgrade", "head", database_url=scratch_database_url)
    assert again.returncode == 0, again.stderr
    assert current_revision(scratch_database_url) == ["0001"]


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
