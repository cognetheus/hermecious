"""Environment-driven settings shared by the API, the worker and migrations.

This is the single settings component. Required settings have no defaults: a
missing or invalid value stops startup. Errors name the offending settings but
never echo their values, and the settings repr masks every URL.
"""

from typing import Any, Literal

from pydantic import Field, PostgresDsn, RedisDsn, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class SettingsError(RuntimeError):
    """Raised when required settings are missing or invalid."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__("missing or invalid settings: " + ", ".join(names))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    environment: Environment = Field(validation_alias="HERMECIOUS_ENV")
    log_level: LogLevel = Field(default="INFO", validation_alias="HERMECIOUS_LOG_LEVEL")
    database_url: PostgresDsn
    redis_url: RedisDsn

    @model_validator(mode="after")
    def _production_is_strict(self) -> "Settings":
        if self.environment == "production" and self.log_level == "DEBUG":
            raise ValueError("HERMECIOUS_LOG_LEVEL")
        return self

    def __repr_args__(self) -> Any:
        for name, value in super().__repr_args__():
            yield name, ("***" if name in {"database_url", "redis_url"} else value)


def _setting_names(exc: ValidationError) -> list[str]:
    names: set[str] = set()
    for error in exc.errors():
        if error["loc"]:
            names.add(str(error["loc"][0]).upper())
        else:  # model-level rule; its message is the offending setting's name
            names.add(str(error.get("ctx", {}).get("error", "SETTINGS")).upper())
    return sorted(names)


def load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # populated from the environment
    except ValidationError as exc:
        # `from None` drops the pydantic error, whose text includes input values.
        raise SettingsError(_setting_names(exc)) from None
