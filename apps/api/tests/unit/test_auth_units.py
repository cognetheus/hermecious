"""Session tokens, CSRF derivation, password policy and AUTH-09 security configuration."""

import uuid

import pytest
from pydantic import ValidationError

from app.auth import passwords, tokens
from tests.factories import make_settings


def test_cookie_round_trip_and_entropy() -> None:
    token = tokens.new_token()
    assert tokens.parse_cookie(token.cookie_value) == token
    assert len(token.verifier) == 43  # 32 bytes, base64url without padding
    assert len({tokens.new_token().verifier for _ in range(1_000)}) == 1_000


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "abc",
        f"{uuid.uuid4().hex}",
        f"{uuid.uuid4().hex}.short",
        f"{uuid.uuid4().hex}.{'A' * 43}.extra",
        f"{uuid.uuid4().hex.upper()}.{'A' * 43}",
        f"{uuid.uuid4().hex}.{'A' * 42}=",
        f"{uuid.uuid4()}.{'A' * 43}",
    ],
)
def test_malformed_cookies_parse_to_none(value: str | None) -> None:
    assert tokens.parse_cookie(value) is None


def test_hash_is_not_the_verifier_and_compare_is_exact() -> None:
    token = tokens.new_token()
    stored = tokens.verifier_hash(token.verifier)
    assert len(stored) == 64 and token.verifier not in stored
    assert tokens.verifier_matches(token.verifier, stored)
    assert not tokens.verifier_matches(tokens.new_token().verifier, stored)


def test_csrf_is_bound_to_the_session_verifier() -> None:
    a, b = tokens.new_token(), tokens.new_token()
    assert tokens.csrf_matches(a.verifier, tokens.csrf_token(a.verifier))
    assert not tokens.csrf_matches(a.verifier, tokens.csrf_token(b.verifier))
    assert not tokens.csrf_matches(a.verifier, None)
    assert not tokens.csrf_matches(a.verifier, "")
    assert not tokens.csrf_matches(a.verifier, "ü" * 43)
    assert a.verifier not in tokens.csrf_token(a.verifier)


def test_password_policy_and_unknown_user_verification() -> None:
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.check_policy("short", "a@b.example")
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.check_policy("Owner@Example.com", "owner@example.com")
    passwords.check_policy("correct-horse-battery-staple", "owner@example.com")
    assert passwords.verify_password(None, "anything-at-all-123") is False
    hashed = passwords.hash_password("correct-horse-battery-staple")
    assert passwords.verify_password(hashed, "correct-horse-battery-staple")
    assert not passwords.verify_password(hashed, "wrong-horse-battery-staple")
    assert not passwords.verify_password("not-a-hash", "x")


def test_canonical_email() -> None:
    assert passwords.canonical_email("  Owner@School.EXAMPLE ") == "owner@school.example"


# --- AUTH-09 ---------------------------------------------------------------------------------


def production(**overrides: object) -> dict[str, object]:
    return {
        "environment": "production",
        "session_cookie_secure": True,
        "allowed_origins_raw": "https://ops.example.com",
        **overrides,
    }


def test_valid_production_configuration() -> None:
    settings = make_settings(**production())
    assert settings.session_cookie_name == "__Host-hermecious_session"


@pytest.mark.parametrize(
    ("overrides", "setting"),
    [
        ({"session_cookie_secure": False}, "HERMECIOUS_SESSION_COOKIE_SECURE"),
        ({"allowed_origins_raw": "http://ops.example.com"}, "HERMECIOUS_ALLOWED_ORIGINS"),
        ({"allowed_origins_raw": "https://ops.example.com,http://localhost:3000"}, "HERMECIOUS_ALLOWED_ORIGINS"),
        ({"log_level": "DEBUG"}, "HERMECIOUS_LOG_LEVEL"),
    ],
    ids=["insecure-cookie", "http-origin", "mixed-origins", "debug-logging"],
)
def test_unsafe_production_configurations_are_rejected(overrides: dict[str, object], setting: str) -> None:
    with pytest.raises(ValidationError, match=setting):
        make_settings(**production(**overrides))


@pytest.mark.parametrize(
    "origins",
    [
        "*",
        "https://*.example.com",
        "",
        " , ",
        "https://ops.example.com/",
        "https://ops.example.com/app",
        "https://user:pw@ops.example.com",
        "ftp://ops.example.com",
        "ops.example.com",
        "https://ops.example.com?x=1",
    ],
    ids=[
        "wildcard",
        "wildcard-sub",
        "empty",
        "blank",
        "trailing-slash",
        "path",
        "credentials",
        "scheme",
        "bare",
        "query",
    ],
)
def test_origins_must_be_exact_in_every_environment(origins: str) -> None:
    with pytest.raises(ValidationError, match="HERMECIOUS_ALLOWED_ORIGINS"):
        make_settings(allowed_origins_raw=origins)


def test_idle_cannot_exceed_absolute() -> None:
    with pytest.raises(ValidationError, match="HERMECIOUS_SESSION_IDLE_MINUTES"):
        make_settings(session_idle_minutes=600, session_absolute_minutes=300)


def test_development_allows_loopback_http_with_dev_cookie() -> None:
    settings = make_settings(environment="development", allowed_origins_raw="http://localhost:3000")
    assert settings.session_cookie_name == "hermecious_dev_session"
