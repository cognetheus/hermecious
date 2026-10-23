"""Integration tests run only against a disposable test stack (scripts/test-integration.sh).

Fails closed: without HERMECIOUS_ENV=test and a database whose name ends in
`_test`, the whole session aborts instead of touching another database.
"""

import os
from collections.abc import Iterator

import pytest

from app.core.settings import Settings, SettingsError, load_settings


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
