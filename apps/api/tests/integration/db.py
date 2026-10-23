"""Database helpers for integration tests: scratch databases and Alembic in a subprocess."""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from sqlalchemy.engine import URL, make_url

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


@contextmanager
def scratch_database(server_database_url: str, label: str = "scratch") -> Iterator[URL]:
    """A brand-new empty database on the test server, dropped afterwards."""
    server_url = make_url(server_database_url)
    name = f"hermecious_{label}_{uuid.uuid4().hex[:12]}_test"
    admin_dsn = plain(server_url.set(drivername="postgresql"))
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield server_url.set(database=name)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
