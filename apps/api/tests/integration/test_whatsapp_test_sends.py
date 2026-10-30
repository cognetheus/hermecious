"""P5.3 acceptance WATEST-01..09 (API + Postgres; a local fake Graph layer injected in contract_test mode).

WATEST-10 (a real message to a real test phone) needs Meta credentials and owner approval: BLOCKED_EXTERNAL.
Synthetic, zero-filled numbers only; no request leaves the process.
"""

import json
import threading
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.egress.https_client import UpstreamUncertain
from app.whatsapp import service, test_sends
from app.whatsapp.contracts import ProviderConnectionView
from app.whatsapp.models import ProviderTestSend
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_campaigns import plain_account
from tests.integration.test_eligibility import add_contact
from tests.integration.test_research import Org
from tests.integration.test_whatsapp_webhook import PHONE, SECRET, WABA, change, drain, envelope, message, post, status

pytestmark = pytest.mark.usefixtures("app")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "whatsapp"
API = "/api/v1/integrations/whatsapp"
TEST_NUMBER, TEST_DIGITS = "+920000000201", "920000000201"
WAMID = "wamid.SYNTESTSEND000000001"


class FakeGraph:
    """Serves the template pages and scripted `/messages` replies; records every call. No socket is opened."""

    def __init__(self) -> None:
        self.pages = [
            (FIXTURES / "templates_approved_page.json").read_bytes(),
            (FIXTURES / "templates_paused_page.json").read_bytes(),
        ]
        self.sends: list[tuple[int, bytes] | Exception] = []
        self.calls: list[dict[str, Any]] = []
        self.template_override: dict[str, Any] | None = None

    def request_json(
        self, method: str, url: str, *, body: Any = None, query: Any = None, bearer: str | None = None
    ) -> tuple[int, bytes]:
        self.calls.append({"method": method, "url": url, "body": body, "query": dict(query or {})})
        if method == "GET" and url.endswith("/message_templates"):
            if self.template_override is not None:
                return 200, json.dumps({"data": [self.template_override]}).encode()
            return 200, self.pages[1 if (query or {}).get("after") == "QVFIUPAGE2" else 0]
        reply = self.sends.pop(0) if self.sends else (200, self.accepted())
        if isinstance(reply, Exception):
            raise reply
        return reply

    @staticmethod
    def accepted(wamid: str = WAMID) -> bytes:
        return json.dumps({"messaging_product": "whatsapp", "contacts": [{"input": TEST_DIGITS, "wa_id": TEST_DIGITS}],
                           "messages": [{"id": wamid, "message_status": "accepted"}]}).encode()  # fmt: skip

    def posts(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == "POST"]


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    fake = FakeGraph()

    def http(_connection: ProviderConnectionView) -> FakeGraph:
        return fake

    monkeypatch.setattr(test_sends, "CONTRACT_HTTP", http)
    return fake


def configure(app: FastAPI, **over: Any) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={
            "whatsapp_mode": "contract_test", "whatsapp_waba_id": WABA, "whatsapp_phone_number_id": PHONE,
            "whatsapp_app_secret": SecretStr(SECRET), "whatsapp_test_recipients": SecretStr(TEST_NUMBER),
            "whatsapp_test_outbound_enabled": True, **over,
        }
    )  # fmt: skip


@pytest.fixture
def org(app: FastAPI) -> Org:
    configure(app)
    org = Org(app)
    with db(app) as session:
        service.bind_connection(session, actor=org.actor, clock=app.state.clock, settings=app.state.settings)
    return org


@pytest.fixture
def owner(app: FastAPI, org: Org) -> tuple[TestClient, str]:
    client = TestClient(app, raise_server_exceptions=False)
    return client, logged_in(client, "owner@r.example")


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


class Flow:
    def __init__(self, app: FastAPI, owner: tuple[TestClient, str], client: TestClient, operator: str) -> None:
        self.app, self.owner, self.client, self.operator = app, owner, client, operator

    def sync(self) -> Any:
        return self.owner[0].post(f"{API}/templates/sync", headers=mutation_headers(self.owner[1]))

    def template(self, name: str = "hermecious_test_ping") -> str:
        items = self.client.get(f"{API}/templates").json()["items"]
        found: str = next(t["id"] for t in items if t["name"] == name)
        return found

    def register(self, address: str = TEST_NUMBER) -> Any:
        body = {"address": address, "label": "Owner's own phone",
                "consent_statement": "I own this number and agree to receive Hermecious test templates."}  # fmt: skip
        return self.owner[0].post(f"{API}/test-recipients", json=body, headers=mutation_headers(self.owner[1]))

    def preview(
        self, recipient: str, template: str, params: list[str] | None = None, extra: dict[str, str] | None = None
    ) -> Any:
        body = {"recipient_id": recipient, "template_id": template, "parameters": params or ["Owner"],
                "idempotency_key": f"preview-{uuid.uuid4().hex}", **(extra or {})}  # fmt: skip
        return self.client.post(f"{API}/test-sends", json=body, headers=mutation_headers(self.operator))

    def confirm(self, created: dict[str, Any], who: tuple[TestClient, str] | None = None, **over: Any) -> Any:
        client, csrf = who or self.owner
        body = {"preview_digest": created["preview_digest"], "confirmation_nonce": created["confirmation_nonce"]}
        body |= over
        return client.post(f"{API}/test-sends/{created['id']}/confirm", json=body, headers=mutation_headers(csrf))

    def ready(self) -> tuple[str, str]:
        assert self.sync().status_code == 200
        recipient = self.register()
        assert recipient.status_code == 201, recipient.text
        return recipient.json()["id"], self.template()


@pytest.fixture
def flow(app: FastAPI, owner: tuple[TestClient, str], client: TestClient, operator: str, graph: FakeGraph) -> Flow:
    return Flow(app, owner, client, operator)


def sends(app: FastAPI) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(ProviderTestSend)) or 0)


# --- WATEST-01 -----------------------------------------------------------------------------------------------------


def test_watest_01_owner_confirmed_single_recipient_template(
    app: FastAPI, client: TestClient, flow: Flow, graph: FakeGraph
) -> None:
    recipient, template = flow.ready()
    created = flow.preview(recipient, template)
    assert created.status_code == 201, created.text
    preview = created.json()
    assert preview["state"] == "awaiting_confirmation" and preview["label"] == test_sends.CONFIRM_LABEL
    assert preview["preview_text"] == "Hello Owner, this is a Hermecious test message."
    assert (preview["recipient"], preview["template"]["category"]) == ("+92 ••••••• 201", "UTILITY")
    assert graph.posts() == []  # a preview never sends
    assert flow.confirm(preview, who=(client, flow.operator)).status_code == 403  # owners only
    confirmed = flow.confirm(preview)
    assert confirmed.status_code == 200, confirmed.text
    assert (confirmed.json()["state"], confirmed.json()["provider_message_id"]) == ("provider_accepted", WAMID)
    (call,) = graph.posts()
    assert call["url"] == f"https://graph.facebook.com/v26.0/{PHONE}/messages"
    assert call["body"]["to"] == TEST_DIGITS and call["body"]["template"]["name"] == "hermecious_test_ping"
    assert call["body"]["template"]["components"][0]["parameters"] == [{"type": "text", "text": "Owner"}]
    observer = TestClient(app, raise_server_exceptions=False)
    logged_in(observer, "observer@r.example")
    seen = observer.get(f"{API}/test-sends/{preview['id']}").json()
    assert set(seen) == {"id", "state", "delivery", "created_at", "real_message", "label"}  # redacted


# --- WATEST-02 -----------------------------------------------------------------------------------------------------


def test_watest_02_only_a_current_approved_supported_template_is_usable(
    app: FastAPI, flow: Flow, graph: FakeGraph
) -> None:
    recipient, template = flow.ready()
    items = {t["name"]: t for t in flow.client.get(f"{API}/templates").json()["items"]}
    assert set(items) == {"hermecious_test_ping", "promo_paused", "otp_code", "media_header"}  # both pages
    assert [c["query"].get("after") for c in graph.calls if c["method"] == "GET"] == [None, "QVFIUPAGE2"]
    assert (items["promo_paused"]["provider_status"], items["promo_paused"]["usable_for_test"]) == ("PAUSED", False)
    assert items["otp_code"]["usable_for_test"] is False and items["media_header"]["supported"] is False
    for name, reason in (("promo_paused", "not_approved"), ("otp_code", "category_not_allowed"),
                         ("media_header", "unsupported_components")):  # fmt: skip
        refused = flow.preview(recipient, items[name]["id"], [] if name != "otp_code" else ["1"])
        assert refused.status_code == 409 and reason in refused.json()["error"]["message"], name
    created = flow.preview(recipient, template).json()
    graph.template_override = {
        "id": "900000000000001", "name": "hermecious_test_ping", "language": "en_US", "category": "UTILITY",
        "status": "APPROVED", "components": [{"type": "BODY", "text": "Changed wording {{1}}."}],
    }  # fmt: skip
    changed = flow.confirm(created)
    assert changed.status_code == 409 and "template_changed" in changed.json()["error"]["message"]
    graph.template_override = None
    app.state.clock.advance(timedelta(minutes=16))
    flow.client.cookies.clear()
    flow.operator = logged_in(flow.client, "operator@r.example")
    stale = flow.preview(recipient, template, ["Later"])
    assert stale.status_code == 409 and "stale_catalog" in stale.json()["error"]["message"]
    assert graph.posts() == []


# --- WATEST-03 -----------------------------------------------------------------------------------------------------


def test_watest_03_sourced_or_forged_numbers_are_refused_server_side(
    app: FastAPI, client: TestClient, org: Org, flow: Flow, graph: FakeGraph
) -> None:
    assert flow.sync().status_code == 200
    unlisted = flow.register("+92 000 0000299")
    assert unlisted.status_code == 422 and "NOT_ALLOWLISTED" in unlisted.json()["error"]["message"]
    school = plain_account(app, org, "Lahore Lead School (Synthetic)")
    assert add_contact(client, flow.operator, school, TEST_NUMBER).status_code == 201  # now a sourced contact
    sourced = flow.register()
    assert sourced.status_code == 409 and "sourced contact" in sourced.json()["error"]["message"]
    for field in ("phone_number", "body", "campaign_id", "account_id", "recipient_url"):
        forged = flow.preview(str(uuid.uuid4()), flow.template(), extra={field: "+923001234567"})
        assert forged.status_code == 422, field
    assert graph.posts() == [] and sends(app) == 0


# --- WATEST-04 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("change_after_preview", ["revoke", "suppress", "kill_switch", "allowlist", "connection"])
def test_watest_04_changes_after_preview_block_confirmation(
    app: FastAPI, client: TestClient, flow: Flow, graph: FakeGraph, change_after_preview: str
) -> None:
    recipient, template = flow.ready()
    created = flow.preview(recipient, template).json()
    owner_client, csrf = flow.owner
    expected = {
        "revoke": "recipient_revoked", "suppress": "recipient_suppressed", "kill_switch": "test_outbound_disabled",
        "allowlist": "recipient_not_allowlisted", "connection": "connection_mismatch",
    }[change_after_preview]  # fmt: skip
    if change_after_preview == "revoke":
        owner_client.post(f"{API}/test-recipients/{recipient}/revoke", headers=mutation_headers(csrf))
    elif change_after_preview == "suppress":  # an authenticated STOP from the test number itself (P5.2)
        stop = envelope(change(messages=(message("wamid.SYNSTOP0001", sender=TEST_DIGITS, text="STOP"),)))
        assert post(client, stop).status_code == 200
        drain(app)
    elif change_after_preview == "kill_switch":
        configure(app, whatsapp_test_outbound_enabled=False)
    elif change_after_preview == "allowlist":
        configure(app, whatsapp_test_recipients=SecretStr("+920000000999"))
    else:
        configure(app, whatsapp_phone_number_id="200000000000777")
    denied = flow.confirm(created)
    assert denied.status_code == 409 and expected in denied.json()["error"]["message"]
    assert graph.posts() == []
    replay = flow.confirm(created).json()  # denied is final: the recorded outcome stands, a new preview is needed
    assert (replay["state"], replay["denial_reason"], replay["replayed"]) == ("denied", expected, True)
    assert graph.posts() == []


@pytest.mark.parametrize("change_after_preview", ["demoted", "session_revoked"])
def test_watest_04_role_or_session_changes_after_preview_block_confirmation(
    app: FastAPI, org: Org, flow: Flow, graph: FakeGraph, change_after_preview: str
) -> None:
    recipient, template = flow.ready()
    created = flow.preview(recipient, template).json()
    with db(app) as session:  # roles and sessions are re-read from Postgres on every request
        if change_after_preview == "demoted":
            session.execute(text("UPDATE users SET role = 'operator' WHERE id = :u"), {"u": org.owner})
        else:
            session.execute(text("UPDATE auth_sessions SET revoked_at = now()"))
        session.commit()
    expected = 403 if change_after_preview == "demoted" else 401
    assert flow.confirm(created).status_code == expected
    assert graph.posts() == []
    with db(app) as session:
        assert session.scalar(select(ProviderTestSend.state)) == "awaiting_confirmation"


# --- WATEST-05 -----------------------------------------------------------------------------------------------------


def test_watest_05_duplicate_concurrent_and_conflicting_confirmations_send_once(
    app: FastAPI, flow: Flow, graph: FakeGraph
) -> None:
    recipient, template = flow.ready()
    body = {"recipient_id": recipient, "template_id": template, "parameters": ["Owner"],
            "idempotency_key": "send-k-0001"}  # fmt: skip
    first = flow.client.post(f"{API}/test-sends", json=body, headers=mutation_headers(flow.operator))
    replay = flow.client.post(f"{API}/test-sends", json=body, headers=mutation_headers(flow.operator))
    assert (first.status_code, replay.status_code, replay.json()["confirmation_nonce"]) == (201, 200, None)
    changed = flow.client.post(f"{API}/test-sends", json=body | {"parameters": ["Other"]},
                               headers=mutation_headers(flow.operator))  # fmt: skip
    assert changed.status_code == 409
    created = first.json()
    assert flow.confirm(created, confirmation_nonce="x" * 43).status_code == 409  # wrong nonce consumes nothing
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def race() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        csrf = logged_in(local, "owner@r.example")
        barrier.wait(timeout=10)
        statuses.append(flow.confirm(created, who=(local, csrf)).status_code)

    threads = [threading.Thread(target=race) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [200, 200] and len(graph.posts()) == 1  # one Graph call, the other a replay
    again = flow.confirm(created)
    assert again.status_code == 200 and again.json()["replayed"] is True and len(graph.posts()) == 1


# --- WATEST-06 / 07 ------------------------------------------------------------------------------------------------


def test_watest_06_07_acceptance_is_not_delivery_and_statuses_reconcile_out_of_order(
    app: FastAPI, client: TestClient, flow: Flow, graph: FakeGraph
) -> None:
    recipient, template = flow.ready()
    # A status arrives before the operator even confirms (before correlation): it is parked as an observation.
    post(client, envelope(change(statuses=(status(WAMID, "read", 0.5),))))
    drain(app)
    created = flow.preview(recipient, template).json()
    graph.sends.append((200, FakeGraph.accepted("wamid.SYNTESTSEND000000002")))
    accepted = flow.confirm(created).json()
    assert (accepted["state"], accepted["delivery"]) == (
        "provider_accepted", {"status": "accepted_unknown_delivery", "conflict": None},
    )  # fmt: skip
    wamid = accepted["provider_message_id"]
    for state, minutes in (("read", 0.2), ("sent", 0.4), ("delivered", 0.3)):  # read first, then sent, delivered
        post(client, envelope(change(statuses=(status(wamid, state, minutes),))))
        drain(app)
    shown = flow.client.get(f"{API}/test-sends/{created['id']}").json()
    assert shown["delivery"] == {"status": "read", "conflict": None}  # never regresses to sent
    assert [t["status"] for t in shown["timeline"]] == ["sent", "delivered", "read"]
    second = flow.preview(recipient, template, ["Two"]).json()
    graph.sends.append((200, FakeGraph.accepted(WAMID)))  # the id whose status arrived earlier
    reconciled = flow.confirm(second).json()
    assert reconciled["delivery"]["status"] == "read"  # the parked observation is joined on read


# --- WATEST-08 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "state", "error_class"),
    [
        (UpstreamUncertain(), "indeterminate", "provider_uncertain"),
        ((429, (FIXTURES / "cloud_send_rate_limited.json").read_bytes()), "definitively_rejected", "provider_quota"),
        ((401, (FIXTURES / "cloud_send_unauthorized.json").read_bytes()), "definitively_rejected", "provider_auth"),
        ((200, b'{"messages": []}'), "indeterminate", "provider_uncertain"),
    ],
)
def test_watest_08_timeouts_and_errors_are_typed_and_never_resent(
    app: FastAPI, flow: Flow, graph: FakeGraph, reply: Any, state: str, error_class: str
) -> None:
    recipient, template = flow.ready()
    created = flow.preview(recipient, template).json()
    graph.sends.append(reply)
    result = flow.confirm(created).json()
    assert (result["state"], result["error_class"], result["provider_message_id"]) == (state, error_class, None)
    assert flow.confirm(created).json()["replayed"] is True and len(graph.posts()) == 1  # never a blind resend


def test_watest_08_a_stale_reservation_is_only_ever_marked_indeterminate(app: FastAPI, flow: Flow) -> None:
    recipient, template = flow.ready()
    created = flow.preview(recipient, template).json()
    with db(app) as session:  # the worker died after reserving, before recording an outcome
        session.execute(
            text("UPDATE provider_test_sends SET state = 'reserved', confirmed_by = requested_by,"
                 " confirmed_at = updated_at WHERE id = :i"),
            {"i": created["id"]},
        )  # fmt: skip
        session.commit()
    owner_client, csrf = flow.owner
    url = f"{API}/test-sends/{created['id']}/mark-indeterminate"
    assert owner_client.post(url, headers=mutation_headers(csrf)).status_code == 409  # too fresh
    app.state.clock.advance(timedelta(minutes=3))
    owner_client.cookies.clear()
    csrf = logged_in(owner_client, "owner@r.example")
    marked = owner_client.post(url, headers=mutation_headers(csrf)).json()
    assert (marked["state"], marked["error_class"]) == ("indeterminate", "provider_uncertain")


# --- WATEST-09 -----------------------------------------------------------------------------------------------------


def test_watest_09_fails_closed_without_test_mode_binding_or_budget(app: FastAPI, flow: Flow, graph: FakeGraph) -> None:
    recipient, template = flow.ready()
    for _ in range(3):
        created = flow.preview(recipient, template, [f"Run {_}"]).json()
        assert flow.confirm(created).json()["state"] == "provider_accepted"
    fourth = flow.preview(recipient, template, ["Run 4"]).json()
    capped = flow.confirm(fourth)
    assert capped.status_code == 409 and "daily_cap_reached" in capped.json()["error"]["message"]
    assert len(graph.posts()) == 3
    for mode in ("simulation", "production"):
        app.state.settings = app.state.settings.model_copy(update={"whatsapp_mode": mode})
        assert flow.sync().status_code == 409
        assert flow.preview(recipient, template, ["Blocked"]).status_code == 409
    status_view = flow.client.get(f"{API}/connection").json()
    assert status_view["live_outbound_enabled"] is False and status_view["test_sending_available"] is False
