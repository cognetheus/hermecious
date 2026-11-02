"""P5.5 RELEASE-06 / RELEASE-10: the deploy-time live gate can only open in a real production deployment with a named
human approval; CI, development and the committed configuration can never turn on real sending."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from app.release import readiness
from app.release.readiness import Check
from app.release.service import live_gate
from tests.factories import make_settings

ROOT = Path(__file__).parents[4]
NOW = datetime(2026, 10, 30, 7, 0, tzinfo=UTC)
PRODUCTION: dict[str, Any] = {
    "environment": "production", "allowed_origins_raw": "https://app.example.pk", "session_cookie_secure": True,
    "contact_hmac_secrets": "k1:" + "a" * 40, "whatsapp_mode": "production", "whatsapp_waba_id": "100000000000001",
    "whatsapp_phone_number_id": "200000000000002", "whatsapp_production_phone_number_ids": "200000000000002",
    "whatsapp_access_token": "EAA-synthetic-production-token-never-real", "whatsapp_app_secret": "s" * 40,
    "whatsapp_verify_token": "v" * 40, "build_sha": "0123abc",
}  # fmt: skip
APPROVED = {"live_outbound_enabled": True, "live_outbound_approved_by": "Owner Name",
            "live_outbound_approved_at": NOW - timedelta(hours=1)}  # fmt: skip


def settings(**values: Any) -> Settings:
    return make_settings(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "test", "live_outbound_enabled": True},
        {"environment": "development", "live_outbound_enabled": True},
        {**PRODUCTION, "live_outbound_enabled": True},  # no named approval
        {**PRODUCTION, **APPROVED, "build_sha": None},  # unidentified build
        {**PRODUCTION, **APPROVED, "live_outbound_approved_at": datetime.now(UTC) + timedelta(days=1)},  # future
        {**PRODUCTION, **APPROVED, "whatsapp_mode": "provider_test"},  # a Meta test number is not production
        {**PRODUCTION, **APPROVED, "environment": "test"},  # everything approved, but not a production deployment
        {**PRODUCTION, **APPROVED, "environment": "development"},
    ],
)
def test_release_10_the_live_gate_refuses_to_start_outside_an_approved_production_deployment(
    values: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="HERMECIOUS_LIVE_OUTBOUND_ENABLED"):
        settings(**values)


def test_release_06_an_approved_production_deployment_opens_only_the_deploy_time_gate() -> None:
    opened = settings(**PRODUCTION, **APPROVED)
    assert live_gate(opened) is None
    assert live_gate(settings(**PRODUCTION)) == "live_outbound_disabled"
    assert live_gate(settings()) == "not_production_environment"


def test_release_10_committed_configuration_keeps_live_sending_off() -> None:
    env = (ROOT / ".env.example").read_text()
    compose = (ROOT / "compose.yaml").read_text()
    assert "HERMECIOUS_LIVE_OUTBOUND_ENABLED=false" in env
    assert "HERMECIOUS_LIVE_OUTBOUND_ENABLED: ${HERMECIOUS_LIVE_OUTBOUND_ENABLED:-false}" in compose
    assert "HERMECIOUS_LIVE_OUTBOUND_ENABLED=true" not in (ROOT / "scripts" / "test-e2e.sh").read_text()


def test_release_status_is_conservative() -> None:
    def check(state: str) -> Check:
        return Check("x", state, None, "r", "owner")

    assert readiness.status_of([check("VERIFIED"), check("BLOCKED_EXTERNAL")]) == "blocked_external"
    assert readiness.status_of([check("VERIFIED"), check("UNKNOWN"), check("BLOCKED_EXTERNAL")]) == "no_go"
    assert readiness.status_of([check("FAILED")]) == "no_go"
    assert readiness.status_of([check("VERIFIED")]) == "ready_for_operator_review"
