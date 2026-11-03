"""Environment-driven settings shared by the API, the worker and migrations.

This is the single settings component. Required settings have no defaults: a
missing or invalid value stops startup. Errors name the offending settings but
never echo their values, and the settings repr masks every URL.
"""

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, ValidationError, field_validator, model_validator
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
    # P4.3 (ADR-022): "key_id:secret[,key_id:secret...]", newest first. Contact addresses are stored only as keyed
    # HMAC digests. Required in production; unset elsewhere, contact endpoints refuse (no built-in key).
    contact_hmac_secrets: SecretStr | None = Field(default=None, validation_alias="HERMECIOUS_CONTACT_HMAC_SECRETS")
    # P5.4 (ADR-029): "key_id:secret[,...]", newest first. Inbound WhatsApp text is kept only sealed (AES-256-GCM)
    # under these keys and only for a bounded time; unset, no inbound text is kept at all (P5.2 minimization).
    inbound_content_secrets: SecretStr | None = Field(
        default=None, validation_alias="HERMECIOUS_INBOUND_CONTENT_SECRETS"
    )
    # Global outreach stop: when true, every channel-eligibility decision is `deny` (kill_switch_engaged).
    outreach_kill_switch: bool = Field(default=False, validation_alias="HERMECIOUS_OUTREACH_KILL_SWITCH")
    # P5.5 (ADR-030): the deploy-time live gate. `true` refuses to start unless this is a production environment in
    # WhatsApp production mode with an identified build and a named human approval. It is necessary, never
    # sufficient: each send also needs a fresh ready assessment, an owner pilot authorization and every per-send check.
    live_outbound_enabled: bool = Field(default=False, validation_alias="HERMECIOUS_LIVE_OUTBOUND_ENABLED")
    live_outbound_approved_by: str | None = Field(
        default=None, max_length=120, validation_alias="HERMECIOUS_LIVE_OUTBOUND_APPROVED_BY"
    )
    live_outbound_approved_at: datetime | None = Field(
        default=None, validation_alias="HERMECIOUS_LIVE_OUTBOUND_APPROVED_AT"
    )
    # The deployed commit, recorded on every readiness assessment.
    build_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$", validation_alias="HERMECIOUS_BUILD_SHA")
    # P5.1 (ADR-026): WhatsApp Cloud API binding. See app/whatsapp/config.py for the per-mode rules.
    whatsapp_mode: Literal["simulation", "contract_test", "provider_test", "production"] = Field(
        default="simulation", validation_alias="HERMECIOUS_WHATSAPP_MODE"
    )
    whatsapp_graph_version: str = Field(default="v26.0", validation_alias="HERMECIOUS_WHATSAPP_GRAPH_VERSION")
    whatsapp_waba_id: str | None = Field(default=None, validation_alias="HERMECIOUS_WHATSAPP_WABA_ID")
    whatsapp_phone_number_id: str | None = Field(default=None, validation_alias="HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_access_token: SecretStr | None = Field(default=None, validation_alias="HERMECIOUS_WHATSAPP_ACCESS_TOKEN")
    whatsapp_app_secret: SecretStr | None = Field(default=None, validation_alias="HERMECIOUS_WHATSAPP_APP_SECRET")
    whatsapp_verify_token: SecretStr | None = Field(default=None, validation_alias="HERMECIOUS_WHATSAPP_VERIFY_TOKEN")
    # Known production phone-number IDs: provider_test refuses to run against any of them.
    whatsapp_production_phone_number_ids: str = Field(
        default="", validation_alias="HERMECIOUS_WHATSAPP_PRODUCTION_PHONE_NUMBER_IDS"
    )
    # provider_test only: who confirmed (Meta dashboard checklist) that the WABA and phone are Meta test assets.
    whatsapp_test_identity_confirmed_by: str | None = Field(
        default=None, max_length=120, validation_alias="HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_BY"
    )
    whatsapp_test_identity_confirmed_at: datetime | None = Field(
        default=None, validation_alias="HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_AT"
    )
    # P5.3: server-side allowlist of operator-owned test recipients ("+92...,+44..."). Personal data: masked in repr.
    whatsapp_test_recipients: SecretStr | None = Field(
        default=None, validation_alias="HERMECIOUS_WHATSAPP_TEST_RECIPIENTS"
    )
    # P5.2 reversible processing stop (runbook §1): signed items keep being stored; processing waits until false.
    whatsapp_inbox_paused: bool = Field(default=False, validation_alias="HERMECIOUS_WHATSAPP_INBOX_PAUSED")
    # P5.3 separate test-outbound kill switch; off by default and never a production override.
    whatsapp_test_outbound_enabled: bool = Field(
        default=False, validation_alias="HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED"
    )

    @field_validator(
        "contact_hmac_secrets",
        "inbound_content_secrets",
        "whatsapp_waba_id",
        "whatsapp_phone_number_id",
        "whatsapp_access_token",
        "whatsapp_app_secret",
        "whatsapp_verify_token",
        "whatsapp_test_identity_confirmed_by",
        "whatsapp_test_identity_confirmed_at",
        "whatsapp_test_recipients",
        "live_outbound_approved_by",
        "live_outbound_approved_at",
        "build_sha",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

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
            if self.osm_rights_reviewed_at > datetime.now(UTC):  # a future review date would never expire
                raise ValueError("HERMECIOUS_OSM_REVIEWED_AT")
            if not self.osm_bbox_citation:
                raise ValueError("HERMECIOUS_OSM_BBOX_CITATION")
            try:
                parse_bbox(self.osm_bbox or "")
            except BBoxError:
                raise ValueError("HERMECIOUS_OSM_BBOX") from None
        if self.contact_hmac_secrets is not None:
            from app.contacts.addresses import KeyringError, parse_keyring  # noqa: PLC0415

            try:
                parse_keyring(self.contact_hmac_secrets.get_secret_value())
            except KeyringError:
                raise ValueError("HERMECIOUS_CONTACT_HMAC_SECRETS") from None
        if self.inbound_content_secrets is not None:
            from app.contacts.addresses import KeyringError, parse_keyring  # noqa: PLC0415

            try:
                parse_keyring(self.inbound_content_secrets.get_secret_value())
            except KeyringError:
                raise ValueError("HERMECIOUS_INBOUND_CONTENT_SECRETS") from None
        if self.live_outbound_enabled and (  # never in test, development or CI (ADR-030)
            self.environment != "production"
            or self.whatsapp_mode != "production"
            or not self.build_sha
            or not self.live_outbound_approved_by
            or self.live_outbound_approved_at is None
            or self.live_outbound_approved_at.tzinfo is None
            or self.live_outbound_approved_at > datetime.now(UTC)
        ):
            raise ValueError("HERMECIOUS_LIVE_OUTBOUND_ENABLED")
        from app.whatsapp.config import whatsapp_setting_error  # noqa: PLC0415

        if (offending := whatsapp_setting_error(self)) is not None:
            raise ValueError(offending)
        if self.environment == "production":
            if self.contact_hmac_secrets is None:
                raise ValueError("HERMECIOUS_CONTACT_HMAC_SECRETS")
            if self.log_level == "DEBUG":
                raise ValueError("HERMECIOUS_LOG_LEVEL")
            if not self.session_cookie_secure:
                raise ValueError("HERMECIOUS_SESSION_COOKIE_SECURE")
            if any(urlsplit(o).scheme != "https" for o in origins):
                raise ValueError("HERMECIOUS_ALLOWED_ORIGINS")
        return self

    def __repr_args__(self) -> Any:
        for name, value in super().__repr_args__():
            yield name, ("***" if name in {"database_url", "redis_url"} else value)  # SecretStr fields mask themselves


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
