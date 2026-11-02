"""P5.5 acceptance RELEASE-01..10 (API + Postgres). Fake transports only: no request can reach Meta.

The pilot world is a real (non-fixture) organization: a passed 30-school P3.4 evaluation, a live campaign, verified
opt-in evidence, P4.4 approved content bound to a Meta template from a (faked) production catalog, signed webhook
traffic and owner attestations. Every number is synthetic and zero-filled.
"""

import json
import threading
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.approvals import service as approvals
from app.core.settings import Settings
from app.egress import https_client
from app.egress.https_client import UpstreamUncertain
from app.release import pilot
from app.release import service as release
from app.release.models import PilotSend
from app.whatsapp import service as connections
from app.whatsapp import transport as wa
from app.whatsapp.contracts import ProviderConnectionView
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_campaigns import approve as approve_member
from tests.integration.test_campaigns import item, new_campaign, preview
from tests.integration.test_drafts import draft
from tests.integration.test_eligibility import add_contact, record, review, revoke, suppress
from tests.integration.test_evaluation import Team, judge
from tests.integration.test_evaluation import create as create_eval
from tests.integration.test_evaluation import detail as eval_detail
from tests.integration.test_evaluation import finalize as finalize_eval
from tests.integration.test_qualification import assess, publish_offer
from tests.integration.test_whatsapp_webhook import change, drain, envelope, message, sign, status

pytestmark = pytest.mark.usefixtures("app")
API = "/api/v1/release/whatsapp"
WABA, PHONE = "100000000000001", "200000000000002"
SECRET = "synthetic-production-app-secret-0123456789"
NUMBER, DIGITS = "+920000000301", "920000000301"
TEMPLATE_ID = "900000000000010"
TOKEN = "EAA-synthetic-production-token-never-real"
ATTESTATIONS = ("meta_business_verification", "pakistan_legal_review", "real_test_receipt", "operations_readiness")


def catalog(status: str = "APPROVED", body: str = "Assalam o alaikum {{1}}, a short note about admissions.") -> bytes:
    return json.dumps({"data": [{
        "id": TEMPLATE_ID, "name": "school_intro", "language": "en_US", "category": "MARKETING", "status": status,
        "components": [{"type": "BODY", "text": body}],
    }]}).encode()  # fmt: skip


class Graph:
    """A local stand-in for Graph: the catalog page and scripted `/messages` replies. Records every call."""

    def __init__(self) -> None:
        self.page = catalog()
        self.sends: list[tuple[int, bytes] | Exception] = []
        self.calls: list[dict[str, Any]] = []
        self.during_catalog: Any = None

    def request_json(self, method: str, url: str, *, body: Any = None, query: Any = None, bearer: Any = None) -> Any:
        self.calls.append({"method": method, "url": url, "body": body})
        if method == "GET":
            if self.during_catalog is not None:
                self.during_catalog()
            return 200, self.page
        reply = self.sends.pop(0) if self.sends else (200, json.dumps({
            "messaging_product": "whatsapp", "contacts": [{"input": DIGITS, "wa_id": DIGITS}],
            "messages": [{"id": f"wamid.SYNPILOT{len(self.posts()):04d}", "message_status": "accepted"}],
        }).encode())  # fmt: skip
        if isinstance(reply, Exception):
            raise reply
        return reply

    def posts(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == "POST"]


@pytest.fixture
def no_egress(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def refuse(self: Any, method: str, url: str, **_: Any) -> Any:
        attempts.append(url)
        raise AssertionError("egress attempted")

    monkeypatch.setattr(https_client.PinnedHttpsClient, "request_json", refuse)
    return attempts


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> Graph:
    fake = Graph()

    def reader(settings: Settings, connection: ProviderConnectionView, now: Any) -> wa.MetaCloudTransport:
        return wa.MetaCloudTransport(connection, fake, lambda: TOKEN, now, can_send=False)

    def sender(settings: Settings, connection: ProviderConnectionView, now: Any) -> wa.MetaCloudTransport:
        assert release.live_gate(settings) is None  # the real constructor's precondition, kept in the fake
        return wa.MetaCloudTransport(connection, fake, lambda: TOKEN, now)

    monkeypatch.setattr(release, "_reader", reader)
    monkeypatch.setattr(pilot, "_transport", sender)
    return fake


def production(app: FastAPI, **over: Any) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={
            "environment": "production", "whatsapp_mode": "production", "whatsapp_waba_id": WABA,
            "whatsapp_phone_number_id": PHONE, "whatsapp_production_phone_number_ids": PHONE,
            "whatsapp_access_token": SecretStr(TOKEN), "whatsapp_app_secret": SecretStr(SECRET),
            "build_sha": "0123abc", **over,
        }
    )  # fmt: skip


def webhook(client: TestClient, body: dict[str, Any]) -> Any:
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-Hub-Signature-256": sign(raw, SECRET)}
    return client.post("/api/v1/integrations/whatsapp/webhook", content=raw, headers=headers)


class World:
    def __init__(self, app: FastAPI, graph: Graph) -> None:
        self.app, self.graph = app, graph
        self.team = Team(app, "pl")
        accounts = self.team.schools(30)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.operator = logged_in(self.client, "operator@pl.example")
        self.owner_client = TestClient(app, raise_server_exceptions=False)
        self.owner = logged_in(self.owner_client, "owner@pl.example")
        c, csrf = self.client, self.operator
        run = create_eval(c, csrf, seed="pilot").json()
        for row in eval_detail(c, run["id"])["item_list"]:
            judge(c, csrf, run["id"], row, "supported")
        assert finalize_eval(c, csrf, run["id"]).json()["state"] == "PASSED"
        self.offer = publish_offer(app, self.team)  # type: ignore[arg-type]
        self.account, self.accounts = accounts[0], accounts
        assess(c, csrf, self.account, self.offer)
        production(app)
        with db(app) as session:
            connections.bind_connection(session, actor=self.team.actor, clock=app.state.clock,
                                        settings=app.state.settings)  # fmt: skip
        assert self.owner_post("/catalog/sync").status_code == 200
        live = new_campaign(c, csrf, self.offer, mode="live", rules={"decisions": ["investigate", "contact_now"]})
        self.campaign = live.json()
        row = item(preview(c, self.campaign["id"]), self.account)
        assert approve_member(c, csrf, self.campaign, row).status_code == 200, row
        created = draft(c, csrf, self.campaign["id"], self.account)
        assert created.status_code == 201, created.text
        self.draft = created.json()
        self.contact = add_contact(c, csrf, self.account, NUMBER).json()["id"]
        self.permission = record(c, csrf, self.contact).json()["permission_id"]
        assert review(self.owner_client, self.owner, self.contact, self.permission).status_code == 201
        approval = c.post(f"/api/v1/drafts/{self.draft['id']}/approve", json={
            "content_digest": self.draft["content_digest"], "contact_id": self.contact,
            "template_ref": f"meta:{TEMPLATE_ID}", "reason": "Grounded and polite; checked against the evidence",
            "idempotency_key": f"apr-{uuid.uuid4().hex[:12]}",
        }, headers=mutation_headers(csrf))  # fmt: skip
        assert approval.status_code == 201, approval.text
        assert webhook(c, envelope(change(statuses=(status("wamid.SYNHEALTH01", "delivered", 1),)))).status_code == 200
        for kind in ATTESTATIONS:
            body = {"kind": kind, "statement": f"Owner confirmed {kind.replace('_', ' ')} for the pilot.",
                    "evidence_ref": f"doc://owner/{kind}/2026-10-22"}  # fmt: skip
            assert self.owner_post("/attestations", body).status_code == 201

    def approve_another(self, index: int, number: str) -> dict[str, Any]:
        """A second account in the same live campaign with its own opted-in contact and current approval."""
        c, csrf, account = self.client, self.operator, self.accounts[index]
        assess(c, csrf, account, self.offer)
        campaign = c.get(f"/api/v1/campaigns/{self.campaign['id']}").json()
        assert approve_member(c, csrf, campaign, item(preview(c, campaign["id"]), account)).status_code == 200
        created = draft(c, csrf, campaign["id"], account).json()
        contact = add_contact(c, csrf, account, number).json()["id"]
        permission = record(c, csrf, contact).json()["permission_id"]
        assert review(self.owner_client, self.owner, contact, permission).status_code == 201
        self.app.state.clock.advance(timedelta(seconds=1))  # the newer approval
        approval = c.post(f"/api/v1/drafts/{created['id']}/approve", json={
            "content_digest": created["content_digest"], "contact_id": contact,
            "template_ref": f"meta:{TEMPLATE_ID}", "reason": "Grounded and polite; checked against the evidence",
            "idempotency_key": f"apr-{uuid.uuid4().hex[:12]}",
        }, headers=mutation_headers(csrf))  # fmt: skip
        assert approval.status_code == 201, approval.text
        return dict(created)

    def owner_post(self, path: str, body: Any = None) -> Any:
        return self.owner_client.post(f"{API}{path}", json=body or {}, headers=mutation_headers(self.owner))

    def ready(self) -> dict[str, Any]:
        assessment = self.owner_post("/readiness/evaluate").json()
        assert assessment["status"] == "ready_for_operator_review", [
            c for c in assessment["checks"] if c["status"] != "VERIFIED"
        ]
        return dict(assessment)

    def authorize(self, **over: Any) -> dict[str, Any]:
        body = {"assessment_id": self.ready()["id"], "acknowledgement": release.PILOT_ACK, "purpose": "marketing",
                "max_per_day": 3, "days": 7, **over}  # fmt: skip
        created = self.owner_post("/pilot", body)
        assert created.status_code == 201, created.text
        return dict(created.json())

    def go_live(self, **over: Any) -> None:
        production(self.app, live_outbound_enabled=True, **over)

    def preview(self, params: list[str] | None = None, key: str | None = None) -> Any:
        body = {"draft_id": self.draft["id"], "parameters": params or ["Principal"],
                "idempotency_key": key or f"pilot-{uuid.uuid4().hex[:12]}"}  # fmt: skip
        return self.client.post(f"{API}/pilot-sends", json=body, headers=mutation_headers(self.operator))

    def confirm(self, created: dict[str, Any], number: str = NUMBER, who: tuple[TestClient, str] | None = None,
                **over: Any) -> Any:  # fmt: skip
        client, csrf = who or (self.owner_client, self.owner)
        body = {"preview_digest": created["preview_digest"], "confirmation_nonce": created["confirmation_nonce"],
                "recipient_number": number, **over}  # fmt: skip
        return client.post(f"{API}/pilot-sends/{created['id']}/confirm", json=body, headers=mutation_headers(csrf))


REAL_DEPENDENCIES = approvals.dependencies


@pytest.fixture
def production_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST SEAM (ADR-030 §6): P4.4 has no production content approval yet; it refuses every non-fixture campaign
    with `production_approval_unavailable`. This drops exactly that one reason so the pilot's own mechanics can be
    exercised; every other P4.4 dependency (grounding, eligibility, versions, staleness) stays real.
    `test_release_03_…` proves the unpatched gate keeps production closed."""

    def without_gap(db: Any, d: Any, now: Any, environment: str) -> list[str]:
        return [r for r in REAL_DEPENDENCIES(db, d, now, environment) if r != "production_approval_unavailable"]

    monkeypatch.setattr(approvals, "dependencies", without_gap)


@pytest.fixture
def world(app: FastAPI, graph: Graph, no_egress: list[str], production_approval: None) -> World:
    return World(app, graph)


def denied(response: Any, reason: str) -> bool:
    return response.status_code == 409 and reason in response.json()["error"]["message"]


# --- RELEASE-07 (happy path first: everything else is a deviation from it) ----------------------------------------


def test_release_07_owner_confirmed_exact_revision_single_send(world: World, no_egress: list[str]) -> None:
    world.authorize()
    world.go_live()
    created = world.preview()
    assert created.status_code == 201, created.text
    p = created.json()
    assert (p["state"], p["template"]["name"], p["parameters"]) == ("awaiting_confirmation", "school_intro",
                                                                   ["Principal"])  # fmt: skip
    assert world.confirm(p, who=(world.client, world.operator)).status_code == 403  # owners only
    assert denied(world.confirm(p, number="+920000000999"), "does not match the approved contact")  # not consumed
    sent = world.confirm(p)
    assert sent.status_code == 200, sent.text
    assert (sent.json()["state"], sent.json()["delivery"]["status"]) == (
        "provider_accepted",
        "accepted_unknown_delivery",
    )
    (call,) = world.graph.posts()
    assert call["url"] == f"https://graph.facebook.com/v26.0/{PHONE}/messages"
    assert call["body"]["to"] == DIGITS and call["body"]["template"]["name"] == "school_intro"
    assert world.confirm(p).json()["replayed"] is True and len(world.graph.posts()) == 1
    assert no_egress == []


def sends(app: FastAPI) -> list[PilotSend]:
    with db(app) as session:
        return list(session.scalars(select(PilotSend).order_by(PilotSend.created_at)))


def evaluate_as(app: FastAPI, prefix: str) -> dict[str, Any]:
    client = TestClient(app, raise_server_exceptions=False)
    csrf = logged_in(client, f"owner@{prefix}.example")
    result = client.post(f"{API}/readiness/evaluate", headers=mutation_headers(csrf))
    assert result.status_code == 201, result.text
    found: dict[str, Any] = result.json()
    return found


def by_code(assessment: dict[str, Any]) -> dict[str, str]:
    return {c["code"]: c["status"] for c in assessment["checks"]}


# --- RELEASE-01 / RELEASE-02 / RELEASE-04 (prerequisites) ----------------------------------------------------------


def test_release_01_02_04_missing_identity_receipt_audit_consent_or_review_is_never_ready(
    app: FastAPI, no_egress: list[str]
) -> None:
    team = Team(app, "nx")
    nothing = evaluate_as(app, "nx")  # simulation mode, nothing configured or attested
    checks = by_code(nothing)
    assert nothing["status"] == "no_go" and nothing["grants_sending"] is False
    assert nothing["banner"] == "PRODUCTION OUTBOUND DISABLED UNTIL SEPARATE OPERATOR GO-LIVE"
    for code in ("provider_identity", "real_test_receipt", "webhook_health", "template_catalog", "opt_in_evidence",
                 "approved_content", "meta_business_verification", "pakistan_legal_review"):  # fmt: skip
        assert checks[code] == "BLOCKED_EXTERNAL", code
    assert checks["school_evidence_audit"] == "FAILED"  # RELEASE-02: no finalized real P3.4 audit
    assert checks["deployment_identity"] == "UNKNOWN"
    # A Meta *test* number presented as production: the phone is not a configured production phone.
    production(app, whatsapp_production_phone_number_ids="200000000000999")
    with db(app) as session:
        connections.bind_connection(session, actor=team.actor, clock=app.state.clock, settings=app.state.settings)
    assert by_code(evaluate_as(app, "nx"))["provider_identity"] == "FAILED"
    production(app, outreach_kill_switch=True)
    assert by_code(evaluate_as(app, "nx"))["kill_switch"] == "FAILED"
    # A synthetic audit is never the real gate: 30 synthetic schools cannot pass P3.4.
    synthetic = Team(app, "sy")
    synthetic.schools(30, synthetic=True)
    assert by_code(evaluate_as(app, "sy"))["school_evidence_audit"] == "FAILED"


def test_release_02_a_failing_later_audit_invalidates_the_pilot_and_school_activation(
    app: FastAPI, world: World
) -> None:
    world.authorize()
    world.go_live()
    p = world.preview().json()
    app.state.clock.advance(timedelta(seconds=5))  # a later audit, finalized after the passing one
    run = create_eval(world.client, world.operator, seed="later").json()
    for row in eval_detail(world.client, run["id"])["item_list"]:
        judge(world.client, world.operator, run["id"], row, "unsupported")
    assert finalize_eval(world.client, world.operator, run["id"]).json()["state"] == "FAILED"
    assert denied(world.confirm(p), "readiness_invalidated") and world.graph.posts() == []
    fresh = new_campaign(world.client, world.operator, world.offer, mode="live").json()
    assert fresh["approval_blocked_reason"] is not None  # school campaign activation is denied too


# --- RELEASE-03 ----------------------------------------------------------------------------------------------------


def test_release_03_template_status_content_and_revision_are_checked_fresh(
    app: FastAPI, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.authorize()
    world.go_live()
    p = world.preview().json()
    world.graph.page = catalog(status="PAUSED")  # Meta pauses the template after the preview
    assert denied(world.confirm(p), "template_changed")
    world.graph.page = catalog(body="Changed wording {{1}}.")
    assert denied(world.confirm(world.preview().json()), "template_changed")
    world.graph.page = catalog()
    p = world.preview().json()
    newer = draft(world.client, world.operator, world.campaign["id"], world.account)  # the draft is edited
    assert newer.status_code == 201, newer.text
    assert denied(world.confirm(p), "readiness_invalidated")  # the approval is no longer current: readiness first
    assert world.graph.posts() == []
    # Without the test seam, P4.4 has no production approval: readiness and the pilot both stay closed.
    monkeypatch.setattr(approvals, "dependencies", REAL_DEPENDENCIES)
    assert by_code(world.owner_post("/readiness/evaluate").json())["approved_content"] == "BLOCKED_EXTERNAL"
    refused = world.preview()
    assert refused.status_code == 409 and "no current content approval" in refused.json()["error"]["message"]


def test_release_03_this_drafts_approval_is_rechecked_even_when_readiness_is_unchanged(world: World) -> None:
    world.approve_another(1, "+920000000303")  # readiness binds to this newer, still-current approval
    world.authorize()
    world.go_live()
    p = world.preview().json()
    newer = draft(world.client, world.operator, world.campaign["id"], world.account)  # the first draft is edited
    assert newer.status_code == 201, newer.text
    assert denied(world.confirm(p), "approval_stale")  # readiness still matches; the per-send check catches it
    assert world.graph.posts() == []


def test_release_04_consent_revocation_or_suppression_between_preview_and_confirm_blocks(world: World) -> None:
    other = add_contact(world.client, world.operator, world.account, "+920000000302").json()["id"]
    permission = record(world.client, world.operator, other).json()["permission_id"]
    assert review(world.owner_client, world.owner, other, permission).status_code == 201  # readiness keeps opt-in
    world.authorize()
    world.go_live()
    p = world.preview().json()
    assert revoke(world.client, world.operator, world.contact, world.permission, 2).status_code == 201
    refused = world.confirm(p)  # the approval itself goes stale, so readiness catches it before decide() does
    assert denied(refused, "readiness_invalidated") and sends(world.app)[-1].state == "denied"
    p = world.preview()
    assert p.status_code == 409  # and a new preview for it is refused
    assert suppress(world.client, world.operator, other).status_code == 201
    assert world.graph.posts() == []


def test_release_04_opt_out_suppression_blocks_and_past_observations_stay(app: FastAPI, world: World) -> None:
    world.authorize()
    world.go_live()
    first = world.confirm(world.preview().json()).json()
    assert first["state"] == "provider_accepted"
    assert webhook(world.client, envelope(change(statuses=(status(first["provider_message_id"], "delivered", 0.2),)))
                   ).status_code == 200  # fmt: skip
    stop = envelope(change(messages=(message("wamid.SYNPILOTSTOP", sender=DIGITS, text="STOP", minutes_ago=0.1),)))
    assert webhook(world.client, stop).status_code == 200
    drain(app)
    again = world.preview(["Again"])  # an opted-out contact cannot even be previewed
    assert again.status_code == 409 and "eligibility_suppressed" in again.json()["error"]["message"]
    assert len(world.graph.posts()) == 1
    kept = world.client.get(f"{API}/pilot-sends/{first['id']}").json()
    assert (kept["state"], kept["delivery"]["status"]) == ("provider_accepted", "delivered")  # history preserved


# --- RELEASE-05 ----------------------------------------------------------------------------------------------------


def test_release_05_assessments_are_immutable_expiring_tenant_bound_and_secret_free(app: FastAPI, world: World) -> None:
    assessment = world.ready()
    raw = json.dumps(assessment)
    for secret in (TOKEN, SECRET, PHONE, WABA, NUMBER, DIGITS):
        assert secret not in raw  # fingerprints only
    assert assessment["fresh"] is True and len(assessment["digest"]) == 64
    with db(app) as session, pytest.raises(DBAPIError):
        session.execute(text("UPDATE readiness_assessments SET status = 'no_go'"))
        session.commit()
    with db(app) as session, pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM readiness_attestations"))
        session.commit()
    other = Team(app, "ot")
    assert other.org != world.team.org
    stranger = TestClient(app, raise_server_exceptions=False)
    csrf = logged_in(stranger, "owner@ot.example")
    forged = {"assessment_id": assessment["id"], "acknowledgement": release.PILOT_ACK, "purpose": "marketing"}
    assert stranger.post(f"{API}/pilot", json=forged, headers=mutation_headers(csrf)).status_code == 404
    observer = TestClient(app, raise_server_exceptions=False)
    logged_in(observer, "observer@pl.example")
    assert observer.get(f"{API}/readiness").status_code == 403
    bad = world.owner_post("/attestations", {"kind": "pakistan_legal_review", "statement": "x" * 25,
                                             "evidence_ref": "", "is_verified": True})  # fmt: skip
    assert bad.status_code == 422  # a naked boolean is never accepted
    wrong_ack = world.owner_post("/pilot", {"assessment_id": assessment["id"], "acknowledgement": "yes",
                                            "purpose": "marketing"})  # fmt: skip
    assert wrong_ack.status_code == 422
    app.state.clock.advance(timedelta(hours=25))
    world.owner_client.cookies.clear()
    world.owner = logged_in(world.owner_client, "owner@pl.example")
    stale = world.owner_post("/pilot", {"assessment_id": assessment["id"], "acknowledgement": release.PILOT_ACK,
                                        "purpose": "marketing"})  # fmt: skip
    assert stale.status_code == 409 and "expired" in stale.json()["error"]["message"]


# --- RELEASE-06 ----------------------------------------------------------------------------------------------------


def test_release_06_ready_alone_or_pilot_alone_never_sends(world: World) -> None:
    world.ready()
    refused = world.preview()
    assert refused.status_code == 409 and "no active pilot authorization" in refused.json()["error"]["message"]
    world.authorize()
    p = world.preview().json()
    assert denied(world.confirm(p), "live_outbound_disabled")  # the deploy-time gate is independent
    world.go_live(environment="development")
    assert denied(world.confirm(world.preview().json()), "not_production_environment")
    assert world.graph.posts() == [] and all(s.state == "denied" for s in sends(world.app))


# --- RELEASE-07 (bounds) -------------------------------------------------------------------------------------------


def test_release_07_caps_hours_csrf_and_forged_fields_deny(app: FastAPI, world: World) -> None:
    world.authorize(max_per_day=1)
    world.go_live()
    for field in ("phone_number", "template_status", "skip_consent", "campaign_send", "account_id"):
        body = {"draft_id": world.draft["id"], "parameters": ["P"], "idempotency_key": f"forge-{field}", field: "x"}
        assert world.client.post(f"{API}/pilot-sends", json=body,
                                 headers=mutation_headers(world.operator)).status_code == 422, field  # fmt: skip
    p = world.preview().json()
    no_csrf = world.owner_client.post(f"{API}/pilot-sends/{p['id']}/confirm", json={
        "preview_digest": p["preview_digest"], "confirmation_nonce": p["confirmation_nonce"],
        "recipient_number": NUMBER})  # fmt: skip
    assert no_csrf.status_code == 403
    assert denied(world.confirm(p, confirmation_nonce="x" * 43), "does not match the preview")
    assert world.confirm(p).json()["state"] == "provider_accepted"
    assert denied(world.confirm(world.preview(["Two"]).json()), "daily_cap_reached")
    assert len(world.graph.posts()) == 1


def test_release_07_quiet_hours_in_asia_karachi_defer(app: FastAPI, world: World) -> None:
    world.authorize()
    world.go_live()
    app.state.clock.advance(timedelta(hours=11))  # 23:00 Asia/Karachi: outside business hours
    world.owner_client.cookies.clear()
    world.owner = logged_in(world.owner_client, "owner@pl.example")
    world.client.cookies.clear()
    world.operator = logged_in(world.client, "operator@pl.example")
    assert denied(world.confirm(world.preview(["Late"]).json()), "eligibility_defer")
    assert world.graph.posts() == []


# --- RELEASE-08 ----------------------------------------------------------------------------------------------------


def test_release_08_concurrent_confirms_send_once(app: FastAPI, world: World) -> None:
    world.authorize()
    world.go_live()
    p = world.preview().json()
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def race() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        csrf = logged_in(local, "owner@pl.example")
        barrier.wait(timeout=10)
        statuses.append(world.confirm(p, who=(local, csrf)).status_code)

    racers = [threading.Thread(target=race) for _ in range(2)]
    for t in racers:
        t.start()
    for t in racers:
        t.join(timeout=60)
    assert sorted(statuses) == [200, 200] and len(world.graph.posts()) == 1


@pytest.mark.parametrize(
    ("reply", "state", "error_class"),
    [
        (UpstreamUncertain(), "indeterminate", "provider_uncertain"),
        ((429, b'{"error": {"code": 130429, "message": "rate"}}'), "definitively_rejected", "provider_quota"),
        ((401, b'{"error": {"code": 190, "message": "token"}}'), "definitively_rejected", "provider_auth"),
        ((500, b"{}"), "definitively_rejected", "provider_transient"),
    ],
)
def test_release_08_timeouts_and_provider_errors_are_bounded_and_never_retried(
    world: World, reply: Any, state: str, error_class: str
) -> None:
    world.authorize()
    world.go_live()
    p = world.preview().json()
    world.graph.sends.append(reply)
    result = world.confirm(p).json()
    assert (result["state"], result["error_class"], result["provider_message_id"]) == (state, error_class, None)
    assert world.confirm(p).json()["replayed"] is True and len(world.graph.posts()) == 1


def test_release_08_kill_switch_between_reservation_and_call_and_crash_recovery(app: FastAPI, world: World) -> None:
    world.authorize()
    world.go_live()
    p = world.preview().json()

    def engage() -> None:  # the global stop flips while the template is being re-checked with Meta
        app.state.settings = app.state.settings.model_copy(update={"outreach_kill_switch": True})

    world.graph.during_catalog = engage
    stopped = world.confirm(p)
    assert stopped.status_code == 409 and "stopped before the network call" in stopped.json()["error"]["message"]
    assert world.graph.posts() == [] and sends(app)[-1].denial_reason == "stopped_before_send"
    world.graph.during_catalog = None
    world.go_live(outreach_kill_switch=False)
    p = world.preview(["Crash"]).json()
    with db(app) as session:  # a worker died after reserving, before the call
        session.execute(text("UPDATE pilot_sends SET state = 'reserved', confirmed_by = requested_by,"
                             " confirmed_at = updated_at WHERE id = :i"), {"i": p["id"]})  # fmt: skip
        session.commit()
    url = f"/pilot-sends/{p['id']}/mark-indeterminate"
    assert world.owner_post(url).status_code == 409  # too fresh
    app.state.clock.advance(timedelta(minutes=3))
    world.owner_client.cookies.clear()
    world.owner = logged_in(world.owner_client, "owner@pl.example")
    assert world.owner_post(url).json()["state"] == "indeterminate"
    assert world.graph.posts() == []


# --- RELEASE-09 ----------------------------------------------------------------------------------------------------


def test_release_09_takeover_quality_alert_and_revocation_stop_unsent_work(world: World) -> None:
    auth = world.authorize()
    world.go_live()
    p = world.preview().json()
    assert world.owner_post(f"/pilot/{auth['id']}/pause", {"reason": "human_takeover"}).json()["status"] == "paused"
    assert denied(world.confirm(p), "pilot_human_takeover")
    assert world.owner_post(f"/pilot/{auth['id']}/resume").json()["status"] == "active"
    sent = world.confirm(world.preview(["Resumed"]).json()).json()
    assert sent["state"] == "provider_accepted"
    queued = world.preview(["Q"]).json()  # prepared before the alert
    assert world.owner_post(f"/pilot/{auth['id']}/pause", {"reason": "quality_alert"}).status_code == 200
    assert denied(world.confirm(queued), "pilot_quality_alert")
    assert world.preview(["While paused"]).status_code == 409
    assert world.owner_post(f"/pilot/{auth['id']}/revoke").json()["status"] == "revoked"
    refused = world.preview(["After"])
    assert refused.status_code == 409  # no active authorization: nothing new can even be previewed
    assert world.owner_post(f"/pilot/{auth['id']}/resume").status_code == 409  # revocation is final
    assert world.client.get(f"{API}/pilot-sends/{sent['id']}").json()["state"] == "provider_accepted"
    assert len(world.graph.posts()) == 1


# --- RELEASE-10 ----------------------------------------------------------------------------------------------------


def test_release_10_every_automated_send_was_fake_and_nothing_can_reach_meta(
    app: FastAPI, world: World, no_egress: list[str]
) -> None:
    from fastapi.routing import iter_route_contexts  # noqa: PLC0415

    from app.jobs import registry  # noqa: PLC0415

    world.authorize()
    world.go_live()
    world.confirm(world.preview().json())
    assert all(s.simulated_transport for s in sends(app)) and len(sends(app)) == 1
    assert no_egress == []
    assert not [t for t, _v in registry.REGISTRY if any(w in t for w in ("send", "pilot", "dispatch", "release"))]
    paths = {str(c.path) for c in iter_route_contexts(app.routes)}
    assert not [p for p in paths if "bulk" in p or "campaign_send" in p or p.endswith("/send")]
    with db(app) as session:
        audits = session.scalar(
            text("SELECT count(*) FROM action_audits WHERE action_type = 'release.pilot_confirmed'")
        )
    assert audits == 1
