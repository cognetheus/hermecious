"""Environment-driven settings shared by the API and the worker.

Required settings have no defaults: a missing or invalid value stops startup.
Error messages name the offending settings but never echo their values.
"""

from pydantic import PostgresDsn, RedisDsn, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    """Raised when required settings are missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    database_url: PostgresDsn
    redis_url: RedisDsn


def load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # populated from the environment
    except ValidationError as exc:
        names = sorted({str(error["loc"][0]).upper() for error in exc.errors()})
        # `from None` drops the pydantic error, whose text includes input values.
        raise SettingsError("missing or invalid settings: " + ", ".join(names)) from None
