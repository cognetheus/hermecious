from collections.abc import Callable

import pytest

from app.core.settings import SettingsError, load_settings

VALID = {
    "DATABASE_URL": "postgresql://user:db-secret-value@postgres:5432/app",
    "REDIS_URL": "redis://redis:6379/0",
}


SetEnv = Callable[..., None]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SetEnv:
    for name in VALID:
        monkeypatch.delenv(name, raising=False)

    def set_env(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return set_env


def test_loads_valid_settings(env: SetEnv) -> None:
    env(**VALID)
    settings = load_settings()
    assert settings.database_url.hosts()[0]["host"] == "postgres"
    assert str(settings.redis_url) == "redis://redis:6379/0"


def test_missing_settings_are_named(env: SetEnv) -> None:
    with pytest.raises(SettingsError, match="DATABASE_URL, REDIS_URL"):
        load_settings()


def test_empty_value_is_rejected(env: SetEnv) -> None:
    env(**{**VALID, "REDIS_URL": ""})
    with pytest.raises(SettingsError, match="REDIS_URL"):
        load_settings()


def test_invalid_value_is_named_but_never_echoed(env: SetEnv) -> None:
    env(**{**VALID, "DATABASE_URL": "mysql://user:db-secret-value@db/app"})
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    assert "DATABASE_URL" in str(excinfo.value)
    assert "db-secret-value" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__
