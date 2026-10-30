"""WhatsApp mode rules (P5.1, ADR-026). Each mode is an explicit, fail-closed configuration boundary.

- simulation: the P4.5 fake transport only; any Meta credential or ID is refused.
- contract_test: a local fake HTTP layer, test environment only; a real access token is refused.
- provider_test: one confirmed Meta *test* WABA/phone in a non-production environment; never a production phone.
- production: inbound webhooks and read-only templates (P5.2/P5.3); no outbound send until P5.5.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.settings import Settings

SUPPORTED_GRAPH_VERSIONS = frozenset({"v25.0", "v26.0"})  # verified against Meta's changelog on 2026-10-29
GRAPH_HOST = "graph.facebook.com"
_META_ID = re.compile(r"[0-9]{5,20}")


def production_phone_ids(settings: "Settings") -> frozenset[str]:
    return frozenset(p.strip() for p in settings.whatsapp_production_phone_number_ids.split(",") if p.strip())


def test_recipient_numbers(s: "Settings") -> tuple[str, ...] | None:
    """The canonical E.164 test recipients, or None if any entry is invalid. Never logged."""
    from app.contacts.addresses import AddressError, canonical  # noqa: PLC0415

    if s.whatsapp_test_recipients is None:
        return ()
    raw = [p for p in s.whatsapp_test_recipients.get_secret_value().split(",") if p.strip()]
    try:
        numbers = tuple(canonical(p) for p in raw)
    except AddressError:
        return None
    return numbers if 0 < len(numbers) <= 5 else None


def whatsapp_setting_error(s: "Settings") -> str | None:
    """The name of the first offending setting, or None. Never a value."""
    if s.whatsapp_graph_version not in SUPPORTED_GRAPH_VERSIONS:
        return "HERMECIOUS_WHATSAPP_GRAPH_VERSION"
    for name, value in (
        ("HERMECIOUS_WHATSAPP_WABA_ID", s.whatsapp_waba_id),
        ("HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID", s.whatsapp_phone_number_id),
    ):
        if value is not None and not _META_ID.fullmatch(value):
            return name
    if any(not _META_ID.fullmatch(p) for p in production_phone_ids(s)):
        return "HERMECIOUS_WHATSAPP_PRODUCTION_PHONE_NUMBER_IDS"
    credentials = (s.whatsapp_access_token, s.whatsapp_app_secret, s.whatsapp_verify_token)
    if s.whatsapp_mode == "simulation" and (
        any(c is not None for c in credentials) or s.whatsapp_waba_id or s.whatsapp_phone_number_id
    ):
        return "HERMECIOUS_WHATSAPP_MODE"  # a credential next to the no-egress mode is a misconfiguration
    if s.whatsapp_mode == "contract_test" and (s.environment != "test" or s.whatsapp_access_token is not None):
        return "HERMECIOUS_WHATSAPP_MODE"  # local fakes only: no real token, test environment only
    test_modes = ("contract_test", "provider_test")  # contract_test reaches only an injected local fake
    if s.whatsapp_test_outbound_enabled and s.whatsapp_mode not in test_modes:
        return "HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED"
    if s.whatsapp_test_recipients is not None and (
        s.whatsapp_mode not in test_modes or test_recipient_numbers(s) is None
    ):
        return "HERMECIOUS_WHATSAPP_TEST_RECIPIENTS"
    if s.whatsapp_mode == "provider_test":
        if s.environment == "production":
            return "HERMECIOUS_WHATSAPP_MODE"
        required: tuple[tuple[str, object], ...] = (
            ("HERMECIOUS_WHATSAPP_WABA_ID", s.whatsapp_waba_id),
            ("HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID", s.whatsapp_phone_number_id),
            ("HERMECIOUS_WHATSAPP_ACCESS_TOKEN", s.whatsapp_access_token),
            ("HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_BY", s.whatsapp_test_identity_confirmed_by),
            ("HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_AT", s.whatsapp_test_identity_confirmed_at),
        )
        for setting, present in required:
            if present is None:
                return setting
        if s.whatsapp_phone_number_id in production_phone_ids(s):
            return "HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID"  # pointed at a known production number
    if s.whatsapp_mode == "production":
        if s.environment != "production":
            return "HERMECIOUS_WHATSAPP_MODE"
        production: tuple[tuple[str, object], ...] = (
            ("HERMECIOUS_WHATSAPP_WABA_ID", s.whatsapp_waba_id),
            ("HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID", s.whatsapp_phone_number_id),
            ("HERMECIOUS_WHATSAPP_APP_SECRET", s.whatsapp_app_secret),
            ("HERMECIOUS_WHATSAPP_VERIFY_TOKEN", s.whatsapp_verify_token),
        )
        for setting, present in production:
            if present is None:
                return setting
    return None
