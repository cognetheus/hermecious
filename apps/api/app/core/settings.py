"""Environment-driven settings shared by the API, the worker and migrations.

This is the single settings component. Required settings have no defaults: a
missing or invalid value stops startup. Errors name the offending settings but
never echo their values, and the settings repr masks every URL.
"""

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

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
    # Comma-separated exact origins allowed to send cookie-authenticated unsafe requests.
    allowed_origins_raw: str = Field(validation_alias="HERMECIOUS_ALLOWED_ORIGINS")
    session_cookie_secure: bool = Field(default=False, validation_alias="HERMECIOUS_SESSION_COOKIE_SECURE")
    session_idle_minutes: int = Field(default=480, ge=5, le=1440, validation_alias="HERMECIOUS_SESSION_IDLE_MINUTES")
    # P2.2 live source (ADR-013): disabled unless the owner completes the rights review fields.
    osm_enabled: bool = Field(default=False, validation_alias="HERMECIOUS_OSM_ENABLED")
    osm_endpoint: str = Field(
        default="https://overpass-api.de/api/interpreter", validation_alias="HERMECIOUS_OSM_ENDPOINT"
    )
    osm_rights_reviewed_by: str | None = Field(
        default=None, max_length=120, validation_alias="HERMECIOUS_OSM_REVIEWED_BY"
    )
    osm_rights_reviewed_at: datetime | None = Field(default=None, validation_alias="HERMECIOUS_OSM_REVIEWED_AT")
    # "south,west,north,east" chosen and cited by the operator; never derived from a place name.
    osm_bbox: str | None = Field(default=None, validation_alias="HERMECIOUS_OSM_BBOX")
    osm_bbox_citation: str | None = Field(default=None, max_length=300, validation_alias="HERMECIOUS_OSM_BBOX_CITATION")
    # Optional wake-up notification for workers; "none" leaves only DB polling (ADR-011).
    job_notify: Literal["redis", "none"] = Field(default="redis", validation_alias="HERMECIOUS_JOB_NOTIFY")
    session_absolute_minutes: int = Field(
        default=1440, ge=15, le=10080, validation_alias="HERMECIOUS_SESSION_ABSOLUTE_MINUTES"
    )

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(o.strip() for o in self.allowed_origins_raw.split(",") if o.strip())

    @property
    def session_cookie_name(self) -> str:
        return "__Host-hermecious_session" if self.session_cookie_secure else "hermecious_dev_session"

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        # Each rule raises the name of the offending setting, never its value.
        origins = self.allowed_origins
        if not origins or any(not _is_exact_origin(o) for o in origins):
            raise ValueError("HERMECIOUS_ALLOWED_ORIGINS")
        if self.session_idle_minutes > self.session_absolute_minutes:
            raise ValueError("HERMECIOUS_SESSION_IDLE_MINUTES")
        if self.osm_enabled:
            from app.discovery.area import OVERPASS_ENDPOINTS, BBoxError, parse_bbox  # noqa: PLC0415

            if self.osm_endpoint not in OVERPASS_ENDPOINTS:
                raise ValueError("HERMECIOUS_OSM_ENDPOINT")
            if not self.osm_rights_reviewed_by or self.osm_rights_reviewed_at is None:
                raise ValueError("HERMECIOUS_OSM_REVIEWED_BY")
            if self.osm_rights_reviewed_at.tzinfo is None:
                raise ValueError("HERMECIOUS_OSM_REVIEWED_AT")
            if not self.osm_bbox_citation:
                raise ValueError("HERMECIOUS_OSM_BBOX_CITATION")
            try:
                parse_bbox(self.osm_bbox or "")
            except BBoxError:
                raise ValueError("HERMECIOUS_OSM_BBOX") from None
        if self.environment == "production":
            if self.log_level == "DEBUG":
                raise ValueError("HERMECIOUS_LOG_LEVEL")
            if not self.session_cookie_secure:
                raise ValueError("HERMECIOUS_SESSION_COOKIE_SECURE")
            if any(urlsplit(o).scheme != "https" for o in origins):
                raise ValueError("HERMECIOUS_ALLOWED_ORIGINS")
        return self

    def __repr_args__(self) -> Any:
        for name, value in super().__repr_args__():
            yield name, ("***" if name in {"database_url", "redis_url"} else value)


def _is_exact_origin(origin: str) -> bool:
    """scheme://host[:port] with no wildcard, path, query, fragment or credentials."""
    if "*" in origin:
        return False
    parts = urlsplit(origin)
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and parts.username is None
        and parts.path == ""
        and not parts.query
        and not parts.fragment
        and origin == f"{parts.scheme}://{parts.netloc}"
    )


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
