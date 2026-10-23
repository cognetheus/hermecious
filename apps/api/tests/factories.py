"""Shared test settings. Hosts are `.invalid`, so nothing here can reach a real service."""

from typing import Any

from app.core.settings import Settings

TEST_ORIGIN = "http://localhost:3000"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": "postgresql://user:db-secret-value@db.invalid:5432/app",
        "redis_url": "redis://cache.invalid:6379/0",
        "allowed_origins_raw": TEST_ORIGIN,
    }
    values.update(overrides)
    return Settings.model_validate(values)
