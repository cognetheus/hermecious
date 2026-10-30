"""P5.1 WAAD-01..08 and 10 (contract tests against a local fake Graph layer; no network). WAAD-09 is integration."""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.egress.https_client import (
    EgressDenied,
    PinnedHttpsClient,
    ResponseTooLarge,
    UpstreamTransient,
    UpstreamUncertain,
)
from app.simulations.transport import LiveTransportForbidden
from app.whatsapp import transport as wa
from app.whatsapp.contracts import (
    OutboundKind,
    ProviderConnectionView,
    ProviderEnvironment,
    ResolvedRecipient,
    SendIntent,
    TemplateDescriptor,
)
from tests.factories import make_settings

FIXTURES = Path(__file__).parents[1] / "fixtures" / "whatsapp"
NOW = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)
ORG, CONNECTION, RECIPIENT = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
TOKEN = "EAAG-synthetic-test-token-never-real-0123456789"
NUMBER = "+920000000101"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeGraph:
    """Records calls; replies from a script. Never opens a socket."""

    def __init__(self, *replies: tuple[int, bytes] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self, method: str, url: str, *, body: Any = None, query: Any = None, bearer: str | None = None
    ) -> tuple[int, bytes]:
        self.calls.append({"method": method, "url": url, "body": body, "query": query, "bearer": bearer})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def connection(mode: ProviderEnvironment = ProviderEnvironment.CONTRACT_TEST, **over: Any) -> ProviderConnectionView:
    base: dict[str, Any] = {
        "connection_id": CONNECTION, "organization_id": ORG, "waba_id": "100000000000001",
        "phone_number_id": "200000000000002", "graph_version": "v26.0", "mode": mode, "enabled": True,
        "credential_ref": "env:HERMECIOUS_WHATSAPP_ACCESS_TOKEN",
    }  # fmt: skip
    return ProviderConnectionView(**(base | over))


def template(**over: Any) -> TemplateDescriptor:
    base: dict[str, Any] = {
        "waba_id": "100000000000001", "template_id": "300000000000003", "name": "operator_test_ping",
        "language": "en_US", "category": "UTILITY", "provider_status": "APPROVED", "components_digest": "0" * 64,
        "body_parameter_count": 1, "header_parameter_count": 0, "fetched_at_utc": NOW, "source": "contract_fixture",
    }  # fmt: skip
    return TemplateDescriptor(**(base | over))


def intent(**over: Any) -> SendIntent:
    base: dict[str, Any] = {
        "operation_id": uuid.uuid4(), "organization_id": ORG, "provider_connection_id": CONNECTION,
        "purpose": "operator_test", "recipient_ref": RECIPIENT, "kind": OutboundKind.TEMPLATE,
        "template_name": "operator_test_ping", "template_language": "en_US",
        "template_components": [{"type": "body", "parameters": [{"type": "text", "text": "Hermecious check"}]}],
        "draft_revision_digest": None, "approval_id": None, "policy_revision": "eligibility-policy-1.0",
        "created_at_utc": NOW, "idempotency_key": "test-send-0001",
    }  # fmt: skip
    return SendIntent(**(base | over))


RECIPIENT_RESOLVED = ResolvedRecipient(recipient_ref=RECIPIENT, e164=NUMBER)


def transport(graph: FakeGraph, **conn: Any) -> wa.MetaCloudTransport:
    settings = make_settings(whatsapp_mode="contract_test")
    return wa.build_transport(settings, connection(**conn), lambda: NOW, http=graph)


# --- WAAD-01 ------------------------------------------------------------------------------------------------------


def test_waad_01_valid_template_intent_builds_a_capped_typed_payload_and_sends_nothing() -> None:
    graph = FakeGraph()
    payload = transport(graph).build_payload(intent(), RECIPIENT_RESOLVED, template())
    assert payload == {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": "920000000101", "type": "template",
        "template": {"name": "operator_test_ping", "language": {"code": "en_US"},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": "Hermecious check"}]}]},
    }  # fmt: skip
    assert graph.calls == []  # building is not sending
    body = [{"type": "body", "parameters": [{"type": "text", "text": "x"}] * 11}]
    with pytest.raises(ValidationError):
        intent(template_components=body)
    with pytest.raises(ValidationError):
        intent(template_components=[{"type": "body", "parameters": [{"type": "text", "text": "y" * 201}]}])
    with pytest.raises(wa.ProviderCallError, match="placeholders"):
        transport(graph).build_payload(intent(template_components=[]), RECIPIENT_RESOLVED, template())
    for bad in (
        template(provider_status="PENDING"),
        template(provider_status="PAUSED"),
        template(category="AUTHENTICATION"),
        template(category="SOMETHING_NEW"),
        template(name="other_template"),
        template(waba_id="100000000000009"),
    ):
        with pytest.raises(wa.ProviderCallError):
            transport(graph).build_payload(intent(), RECIPIENT_RESOLVED, bad)
    with pytest.raises(wa.ProviderCallError, match="only approved template"):
        transport(graph).build_payload(intent(kind=OutboundKind.SERVICE_TEXT), RECIPIENT_RESOLVED, template())


# --- WAAD-02 ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["phone_number", "to", "recipient_url", "base_url", "body"])
def test_waad_02_untrusted_destination_fields_are_refused(field: str) -> None:
    with pytest.raises(ValidationError):
        intent(**{field: "+923001234567"})


@pytest.mark.parametrize("text", ["visit https://evil.example", "call +92 300 1234567", "www.example.com", "a‮b"])
def test_waad_02_parameters_cannot_smuggle_links_numbers_or_controls(text: str) -> None:
    with pytest.raises(ValidationError):
        intent(template_components=[{"type": "body", "parameters": [{"type": "text", "text": text}]}])


def test_waad_02_host_and_paths_are_fixed_and_ids_must_be_digits() -> None:
    graph = FakeGraph((200, fixture("cloud_send_accepted.json")))
    transport(graph).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert graph.calls[0]["url"] == "https://graph.facebook.com/v26.0/200000000000002/messages"
    bad_ids: list[dict[str, Any]] = [
        {"phone_number_id": "../x"}, {"phone_number_id": "2000000@evil"}, {"graph_version": "v26.0/../x"}
    ]  # fmt: skip
    for bad in bad_ids:
        with pytest.raises(ValidationError):
            connection(**bad)
    client = PinnedHttpsClient(wa.egress_policy(connection()), resolver=lambda _h: pytest.fail("resolved"))
    for url in (
        "https://evil.example/v26.0/200000000000002/messages",
        "https://graph.facebook.com/v26.0/999999999999999/messages",
        "http://graph.facebook.com/v26.0/200000000000002/messages",
    ):
        with pytest.raises(EgressDenied):
            client.request_json("POST", url, body={})
    with pytest.raises(wa.ProviderCallError, match="does not match the intent"):
        other = ResolvedRecipient(recipient_ref=uuid.uuid4(), e164=NUMBER)
        transport(graph).build_payload(intent(), other, template())


# --- WAAD-03 ------------------------------------------------------------------------------------------------------


def test_waad_03_factory_never_elevates_a_mode() -> None:
    graph = FakeGraph()
    with pytest.raises(LiveTransportForbidden):
        wa.build_transport(make_settings(), connection(), lambda: NOW, http=graph)  # simulation (default)
    production = make_settings().model_copy(update={"whatsapp_mode": "production"})
    with pytest.raises(LiveTransportForbidden, match="P5.5"):
        wa.build_transport(production, connection(ProviderEnvironment.PRODUCTION), lambda: NOW, http=graph)
    with pytest.raises(LiveTransportForbidden):
        wa.build_transport(make_settings(whatsapp_mode="contract_test"), connection(), lambda: NOW)  # no fake
    with pytest.raises(LiveTransportForbidden):
        dev = make_settings(whatsapp_mode="contract_test").model_copy(update={"environment": "development"})
        wa.build_transport(dev, connection(), lambda: NOW, http=graph)
    with pytest.raises(wa.ProviderCallError, match="another mode"):
        wa.build_transport(
            make_settings(whatsapp_mode="contract_test"), connection(ProviderEnvironment.PROVIDER_TEST),
            lambda: NOW, http=graph,
        )  # fmt: skip
    provider = make_settings(
        environment="development", whatsapp_mode="provider_test", whatsapp_waba_id="100000000000001",
        whatsapp_phone_number_id="200000000000999", whatsapp_access_token=TOKEN,
        whatsapp_test_identity_confirmed_by="Owner", whatsapp_test_identity_confirmed_at=NOW,
    )  # fmt: skip
    with pytest.raises(wa.ProviderCallError, match="configured credentials"):
        wa.build_transport(provider, connection(ProviderEnvironment.PROVIDER_TEST), lambda: NOW, http=graph)
    with pytest.raises(ValidationError, match="HERMECIOUS_LIVE_OUTBOUND_ENABLED"):
        make_settings(live_outbound_enabled=True)


# --- WAAD-04 ------------------------------------------------------------------------------------------------------


def test_waad_04_accepted_call_is_only_acceptance_never_delivery() -> None:
    graph = FakeGraph((200, fixture("cloud_send_accepted.json")))
    result = transport(graph).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (result.outcome, result.provider_message_id, result.provider_message_status) == (
        "accepted",
        "wamid.SYNTHETICFIXTURE0000000001",
        "accepted",
    )
    assert "delivered" not in result.model_dump_json() and "read" not in result.model_dump()
    held = json.loads(fixture("cloud_send_accepted.json"))
    held["messages"][0]["message_status"] = "held_for_quality_assessment"
    graph = FakeGraph((200, json.dumps(held).encode()))
    assert transport(graph).send_template(intent(), RECIPIENT_RESOLVED, template()).outcome == "accepted"


# --- WAAD-05 ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "name", "error_class", "code", "retriable"),
    [
        (400, "cloud_send_bad_request.json", "provider_bad_request", "132001", False),
        (401, "cloud_send_unauthorized.json", "provider_auth", "190", False),
        (403, "cloud_send_bad_request.json", "provider_auth", "132001", False),
        (429, "cloud_send_rate_limited.json", "provider_quota", "130429", True),
        (400, "cloud_send_rate_limited.json", "provider_quota", "130429", True),
        (503, "cloud_send_server_error.json", "provider_transient", "2", True),
    ],
)
def test_waad_05_provider_errors_are_typed_non_sensitive_and_classified(
    status: int, name: str, error_class: str, code: str, retriable: bool
) -> None:
    graph = FakeGraph((status, fixture(name)))
    result = transport(graph).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (result.outcome, result.error_class, result.provider_error_code, result.retriable) == (
        "definitive_rejected",
        error_class,
        code,
        retriable,
    )
    assert result.provider_message_id is None and "Synthetic fixture" not in result.model_dump_json()
    assert len(graph.calls) == 1  # the transport never retries on its own


# --- WAAD-06 ------------------------------------------------------------------------------------------------------


def test_waad_06_timeout_after_the_write_is_indeterminate_and_never_resent() -> None:
    graph = FakeGraph(UpstreamUncertain())
    result = transport(graph).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (result.outcome, result.error_class, result.retriable, result.provider_message_id) == (
        "indeterminate",
        "provider_uncertain",
        False,
        None,
    )
    assert len(graph.calls) == 1
    before_write = FakeGraph(UpstreamTransient("connect_timeout"))
    early = transport(before_write).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (early.outcome, early.retriable) == ("definitive_rejected", True)  # nothing was written


# --- WAAD-07 ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        (200, b"{not json"),
        (200, b"{}"),
        (200, json.dumps({"messaging_product": "whatsapp", "messages": []}).encode()),
        (200, json.dumps({"messaging_product": "whatsapp", "messages": [{"id": "x"}, {"id": "y"}]}).encode()),
        (200, json.dumps({"messaging_product": "whatsapp", "messages": [{"id": "not-a-wamid"}]}).encode()),
        (
            200,
            json.dumps(
                {
                    "messaging_product": "whatsapp",
                    "messages": [{"id": "wamid.SYNTHETIC00000001", "message_status": "sent"}],
                }
            ).encode(),
        ),
        ResponseTooLarge(),
    ],
)
def test_waad_07_malformed_or_oversized_success_never_invents_an_id(reply: tuple[int, bytes] | Exception) -> None:
    result = transport(FakeGraph(reply)).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (result.outcome, result.provider_message_id) == ("indeterminate", None)


def test_waad_07_non_json_error_body_is_still_typed() -> None:
    result = transport(FakeGraph((400, b"<html>bad</html>"))).send_template(intent(), RECIPIENT_RESOLVED, template())
    assert (result.outcome, result.error_class, result.provider_error_code) == (
        "definitive_rejected",
        "provider_bad_request",
        None,
    )


# --- WAAD-08 ------------------------------------------------------------------------------------------------------


def test_waad_08_token_and_recipient_never_reach_results_logs_or_repr(
    json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    graph = FakeGraph((401, fixture("cloud_send_unauthorized.json")))
    provider = make_settings(
        environment="development", whatsapp_mode="provider_test", whatsapp_waba_id="100000000000001",
        whatsapp_phone_number_id="200000000000002", whatsapp_access_token=TOKEN,
        whatsapp_test_identity_confirmed_by="Owner", whatsapp_test_identity_confirmed_at=NOW,
    )  # fmt: skip
    sender = wa.build_transport(provider, connection(ProviderEnvironment.PROVIDER_TEST), lambda: NOW, http=graph)
    result = sender.send_template(intent(), RECIPIENT_RESOLVED, template())
    assert graph.calls[0]["bearer"] == TOKEN  # only as the bearer header value
    exposed = " ".join([result.model_dump_json(), repr(provider), json.dumps(json_logs(), default=str)])
    for secret in (TOKEN, "920000000101", NUMBER):
        assert secret not in exposed, secret
    assert isinstance(provider.whatsapp_access_token, SecretStr)


# --- WAAD-10 (static part; the P4.5 suites are integration) -----------------------------------------------------


def test_waad_10_no_route_job_or_simulator_path_reaches_the_provider() -> None:
    from app.jobs import registry  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415

    api = Path(__file__).parents[2] / "app"
    users = sorted(str(p.relative_to(api)) for p in api.rglob("*.py") if "app.whatsapp.transport" in p.read_text())
    assert users == []  # P5.1: nothing imports the transport yet (P5.3 adds one guarded caller)
    simulator = "\n".join(p.read_text() for p in (api / "simulations").glob("*.py"))
    assert "app.whatsapp" not in simulator and "graph.facebook.com" not in simulator
    assert not [t for t, _v in registry.REGISTRY if any(w in t for w in ("send", "whatsapp", "dispatch"))]
    egress_users = sorted(str(p.relative_to(api)) for p in api.rglob("*.py") if "app.egress" in p.read_text())
    assert egress_users == ["discovery/osm.py", "whatsapp/transport.py"]
    app = create_app(make_settings())
    assert not [r for r in app.routes if "whatsapp" in getattr(r, "path", "")]


PROVIDER_TEST = {
    "environment": "development", "whatsapp_mode": "provider_test", "whatsapp_waba_id": "100000000000001",
    "whatsapp_phone_number_id": "200000000000002", "whatsapp_access_token": TOKEN,
    "whatsapp_test_identity_confirmed_by": "Owner", "whatsapp_test_identity_confirmed_at": NOW,
}  # fmt: skip


@pytest.mark.parametrize(
    ("overrides", "setting"),
    [
        ({"whatsapp_access_token": TOKEN}, "HERMECIOUS_WHATSAPP_MODE"),  # simulation + credential
        ({"whatsapp_waba_id": "100000000000001"}, "HERMECIOUS_WHATSAPP_MODE"),
        ({"whatsapp_graph_version": "v19.0"}, "HERMECIOUS_WHATSAPP_GRAPH_VERSION"),
        ({"whatsapp_mode": "contract_test", "whatsapp_access_token": TOKEN}, "HERMECIOUS_WHATSAPP_MODE"),
        ({"whatsapp_test_outbound_enabled": True}, "HERMECIOUS_WHATSAPP_TEST_OUTBOUND_ENABLED"),
        (
            {**PROVIDER_TEST, "whatsapp_test_identity_confirmed_by": None},
            "HERMECIOUS_WHATSAPP_TEST_IDENTITY_CONFIRMED_BY",
        ),
        ({**PROVIDER_TEST, "whatsapp_access_token": None}, "HERMECIOUS_WHATSAPP_ACCESS_TOKEN"),
        (
            {**PROVIDER_TEST, "whatsapp_production_phone_number_ids": "200000000000002"},
            "HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID",
        ),
        ({**PROVIDER_TEST, "whatsapp_phone_number_id": "12ab"}, "HERMECIOUS_WHATSAPP_PHONE_NUMBER_ID"),
        ({"whatsapp_mode": "production"}, "HERMECIOUS_WHATSAPP_MODE"),  # not the production environment
        ({"live_outbound_enabled": True}, "HERMECIOUS_LIVE_OUTBOUND_ENABLED"),
    ],
)
def test_waad_03_each_mode_refuses_its_misconfiguration(overrides: dict[str, Any], setting: str) -> None:
    with pytest.raises(ValidationError, match=setting) as excinfo:
        make_settings(**overrides)
    assert TOKEN not in str(excinfo.value)


def test_waad_03_provider_test_is_valid_only_with_every_test_identity_field() -> None:
    settings = make_settings(**PROVIDER_TEST)
    assert settings.whatsapp_mode == "provider_test" and settings.whatsapp_test_outbound_enabled is False
