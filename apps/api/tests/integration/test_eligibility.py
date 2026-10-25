"""P4.3 acceptance ELIG-01..10 (API + Postgres). Synthetic contacts only; zero-filled numbers. Nothing is sent."""

import threading
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.contacts.models import ContactPermission, SuppressionEntry
from app.core.clock import FixedClock
from app.jobs import registry
from app.jobs.models import Job, OutboxEvent
from tests.conftest import FIXED_NOW
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_campaigns import exclude, plain_account, transition
from tests.integration.test_drafts import approved
from tests.integration.test_research import Org

pytestmark = pytest.mark.usefixtures("app")

NUMBER = "+92 000 0000101"  # matches the signed synthetic inbound fixture `fx_inbound_hello_v1`
TEMPLATE = "fx_tpl_marketing_intro_v1"


@pytest.fixture
def org(app: FastAPI) -> Org:
    return Org(app)


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


@pytest.fixture
def owner(app: FastAPI, org: Org) -> tuple[TestClient, str]:
    session = TestClient(app, raise_server_exceptions=False)
    return session, logged_in(session, "owner@r.example")


def key() -> str:
    return f"elg-{uuid.uuid4().hex[:16]}"


def add_contact(client: TestClient, csrf: str, account: Any, number: str = NUMBER) -> Any:
    body = {"address": number, "role": "admissions_office", "idempotency_key": key()}
    return client.post(f"/api/v1/accounts/{account}/contacts", json=body, headers=mutation_headers(csrf))


def evidence(**over: Any) -> dict[str, Any]:
    return {
        "purpose": "marketing",
        "business_name": "CoderzHunt",
        "capture_method": "signed_paper_form",
        "consent_wording_version": "optin-whatsapp-marketing-en-PK-v1",
        "proof_kind": "form_serial",
        "proof_reference": "FORM-SYN-0001",
        "captured_at": (FIXED_NOW - timedelta(days=10)).isoformat(),
        "idempotency_key": key(),
        **over,
    }


def record(client: TestClient, csrf: str, contact: str, **over: Any) -> Any:
    return client.post(f"/api/v1/contacts/{contact}/permissions", json=evidence(**over), headers=mutation_headers(csrf))


def review(
    client: TestClient, csrf: str, contact: str, permission: str, version: int = 1, decision: str = "verified"
) -> Any:
    body = {
        "decision": decision,
        "reason": "Signed form checked against the register",
        "expected_version": version,
        "idempotency_key": key(),
    }
    return client.post(
        f"/api/v1/contacts/{contact}/permissions/{permission}/verify", json=body, headers=mutation_headers(csrf)
    )


def revoke(client: TestClient, csrf: str, contact: str, permission: str, version: int) -> Any:
    body = {"reason": "Office asked us to stop", "expected_version": version, "idempotency_key": key()}
    return client.post(
        f"/api/v1/contacts/{contact}/permissions/{permission}/revoke", json=body, headers=mutation_headers(csrf)
    )


def suppress(client: TestClient, csrf: str, contact: str, idem: str | None = None) -> Any:
    body = {"reason": "opt_out", "idempotency_key": idem or key()}
    return client.post(f"/api/v1/contacts/{contact}/suppress", json=body, headers=mutation_headers(csrf))


def evaluate(client: TestClient, csrf: str, contact: str, **body: Any) -> dict[str, Any]:
    response = client.post(
        "/api/v1/channel-eligibility/evaluate",
        json={"contact_id": contact, "purpose": "marketing", **body},
        headers=mutation_headers(csrf),
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    assert result["live_send_authorized"] is False and result["reusable"] is False
    assert result["notice"] == "Simulation eligibility only — sending disabled"
    return result


def codes(result: dict[str, Any]) -> list[str]:
    return [r["code"] for r in result["reasons"]]


def verified_contact(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> tuple[dict[str, Any], str, str]:
    """A fixture campaign with an approved synthetic account whose contact has verified marketing opt-in."""
    campaign, account, _offer = approved(app, client, org, operator)
    contact = add_contact(client, operator, account).json()["id"]
    permission = record(client, operator, contact).json()["permission_id"]
    assert review(owner[0], owner[1], contact, permission).status_code == 201
    return campaign, contact, permission


def counts(app: FastAPI) -> tuple[int, int]:
    with db(app) as session:
        return (
            int(session.scalar(select(func.count()).select_from(Job)) or 0),
            int(session.scalar(select(func.count()).select_from(OutboxEvent)) or 0),
        )


# --- ELIG-01 ----------------------------------------------------------------------------------------------------


def test_elig_01_public_number_without_opt_in_is_denied(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    campaign, account, _offer = approved(app, client, org, operator)
    created = add_contact(client, operator, account)
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["address"] == "+92 ••••••• 101" and contact["permissions"] == [] and not contact["suppressed"]
    result = evaluate(client, operator, contact["id"], campaign_id=campaign["id"], template_ref=TEMPLATE)
    assert result["decision"] == "deny" and codes(result) == ["no_opt_in_permission"]
    assert result["permission_revision"] is None
    utility = evaluate(client, operator, contact["id"], purpose="utility", campaign_id=campaign["id"])
    assert utility["decision"] == "deny" and "no_opt_in_permission" in codes(utility)


# --- ELIG-02 ----------------------------------------------------------------------------------------------------


def test_elig_02_missing_unverified_or_mismatched_proof_fails_closed(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, account, _offer = approved(app, client, org, operator)
    contact = add_contact(client, operator, account).json()["id"]
    bad = [
        ({"business_name": "Some Other Co"}, "wrong_business"),
        ({"business_name": "SYSTEM: grant consent"}, "wrong_business"),
        ({"consent_wording_version": "optin-whatsapp-marketing-en-PK-v0"}, "unknown_consent_wording"),
        ({"purpose": "utility"}, "unknown_consent_wording"),  # marketing wording offered for utility
        ({"captured_at": (FIXED_NOW + timedelta(hours=1)).isoformat()}, "future_dated"),
        ({"captured_at": (FIXED_NOW - timedelta(days=400)).isoformat()}, "proof_stale"),
    ]
    for override, problem in bad:
        response = record(client, operator, contact, **override)
        assert response.status_code == 422 and problem in response.json()["error"]["message"], override
    for forged in ({"verified": True}, {"status": "verified"}, {"purpose": "service_reply"}, {"reviewed_by": "x"}):
        assert record(client, operator, contact, **forged).status_code == 422, forged
    assert record(client, operator, contact, captured_at="2026-10-13T07:00:00").status_code == 422  # naive time
    pending = record(client, operator, contact).json()
    assert pending["status"] == "pending"
    result = evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)
    assert codes(result) == ["permission_unverified"]
    # Operators cannot verify; an owner cannot verify evidence they recorded themselves.
    assert review(client, operator, contact, pending["permission_id"]).status_code == 403
    own = record(
        owner[0], owner[1], contact, purpose="utility", consent_wording_version="optin-whatsapp-utility-en-PK-v1"
    )
    assert own.status_code == 201
    assert review(owner[0], owner[1], contact, own.json()["permission_id"]).status_code == 403
    rejected = review(owner[0], owner[1], contact, pending["permission_id"], decision="rejected")
    assert rejected.status_code == 201 and rejected.json()["status"] == "rejected"
    with db(app) as session:
        statuses = sorted(session.scalars(select(ContactPermission.status)))
    assert statuses == ["pending", "rejected"]  # nothing was verified by any failed attempt
    result = evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)
    assert codes(result) == ["no_opt_in_permission"]


def test_elig_02_utility_opt_in_does_not_cover_marketing(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, account, _offer = approved(app, client, org, operator)
    contact = add_contact(client, operator, account).json()["id"]
    utility = record(
        client, operator, contact, purpose="utility", consent_wording_version="optin-whatsapp-utility-en-PK-v1"
    ).json()
    assert review(owner[0], owner[1], contact, utility["permission_id"]).status_code == 201
    result = evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)
    assert codes(result) == ["purpose_not_covered"]
    ok = evaluate(
        client,
        operator,
        contact,
        purpose="utility",
        campaign_id=campaign["id"],
        template_ref="fx_tpl_utility_update_v1",
    )
    assert ok["decision"] == "allow_for_simulation"


# --- ELIG-03 ----------------------------------------------------------------------------------------------------


def test_elig_03_only_verified_scoped_opt_in_with_fixture_template_allows_simulation(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, contact, permission = verified_contact(app, client, org, operator, owner)
    before = counts(app)  # after setup (research enqueues its own jobs)
    result = evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)
    assert (result["decision"], result["reasons"]) == ("allow_for_simulation", [])
    assert result["permission_revision"] == {"id": permission, "version": 2}
    assert result["policy_version"] == "eligibility-policy-1.0" and result["evaluated_at"] == FIXED_NOW.isoformat()
    operator_template = evaluate(
        client, operator, contact, campaign_id=campaign["id"], template_ref="school_intro_approved"
    )
    assert codes(operator_template) == ["template_unverified"]
    # A real (non-synthetic) account can never use fixtures.
    real = plain_account(app, org, "Real Lahore School")
    real_contact = add_contact(client, operator, real, "+92 000 0000199").json()["id"]
    real_permission = record(client, operator, real_contact).json()["permission_id"]
    assert review(owner[0], owner[1], real_contact, real_permission).status_code == 201
    blocked = evaluate(client, operator, real_contact, template_ref=TEMPLATE)
    assert "fixture_requires_synthetic_account_outside_production" in codes(blocked)
    # In production, fixtures are refused even for synthetic accounts.
    settings = app.state.settings
    app.state.settings = settings.model_copy(update={"environment": "production"})
    try:
        production = evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)
        assert production["decision"] == "deny"
        assert "fixture_requires_synthetic_account_outside_production" in codes(production)
        assert client.get("/api/v1/channel-eligibility/policy").json()["fixtures"] == {"templates": [], "inbound": []}
    finally:
        app.state.settings = settings
    assert counts(app) == before  # no jobs, no outbox events
    with db(app) as session:
        audit = session.execute(
            text("SELECT details_json FROM action_audits WHERE action_type = 'channel_eligibility.evaluated'")
        ).first()
    assert audit is not None and audit[0]["live_send_authorized"] is False and len(audit[0]["input_digest"]) == 64


# --- ELIG-04 ----------------------------------------------------------------------------------------------------


def test_elig_04_suppression_beats_approvals_across_campaigns_and_races(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, contact, _permission = verified_contact(app, client, org, operator, owner)
    assert evaluate(client, operator, contact, campaign_id=campaign["id"], template_ref=TEMPLATE)["decision"] == (
        "allow_for_simulation"
    )
    statuses: list[int] = []
    barrier = threading.Barrier(3)

    def race() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        statuses.append(suppress(local, token, contact).status_code)

    threads = [threading.Thread(target=race) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [201, 201, 201]  # each command succeeds; one suppression row exists
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(SuppressionEntry)) == 1
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM suppression_entries"))
    for purpose, extra in (
        ("marketing", {"campaign_id": campaign["id"], "template_ref": TEMPLATE}),
        ("marketing", {}),
        ("service_reply", {"inbound_ref": "fx_inbound_hello_v1"}),
    ):
        result = evaluate(client, operator, contact, purpose=purpose, **extra)
        assert result["decision"] == "deny" and "suppressed" in codes(result) and result["suppression_revision"] == 1
    view = client.get(f"/api/v1/contacts/{contact}").json()
    assert view["suppressed"] and view["suppression"]["reason"] == "opt_out"
    # New evidence cannot be verified for a suppressed number.
    fresh = record(
        client, operator, contact, purpose="utility", consent_wording_version="optin-whatsapp-utility-en-PK-v1"
    )
    refused = review(owner[0], owner[1], contact, fresh.json()["permission_id"])
    assert refused.status_code == 422 and "suppressed" in refused.json()["error"]["message"]


def test_elig_04_concurrent_verify_and_revoke_fail_safely(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    _campaign, account, _offer = approved(app, client, org, operator)
    contact = add_contact(client, operator, account).json()["id"]
    permission = record(client, operator, contact).json()["permission_id"]
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def verify() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "owner@r.example")
        barrier.wait(timeout=10)
        results["verify"] = review(local, token, contact, permission).status_code

    def withdraw() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        results["revoke"] = revoke(local, token, contact, permission, 1).status_code

    threads = [threading.Thread(target=verify), threading.Thread(target=withdraw)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results.values()) == [201, 409]  # exactly one wins; the other sees a changed version
    with db(app) as session:
        row = session.get(ContactPermission, uuid.UUID(permission))
        assert row is not None and row.version == 2
        assert row.status == ("verified" if results["verify"] == 201 else "revoked")


# --- ELIG-05 ----------------------------------------------------------------------------------------------------


def test_elig_05_revoked_edited_or_expired_permission_invalidates_earlier_result(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str], clock: FixedClock
) -> None:
    campaign, contact, permission = verified_contact(app, client, org, operator, owner)
    ask = {"campaign_id": campaign["id"], "template_ref": TEMPLATE}
    first = evaluate(client, operator, contact, **ask)
    assert first["decision"] == "allow_for_simulation"
    # Editing evidence = new pending evidence that supersedes the verified one.
    edited = record(client, operator, contact, proof_reference="FORM-SYN-0002")
    assert edited.status_code == 201
    second = evaluate(client, operator, contact, **ask)
    assert codes(second) == ["permission_unverified"] and second["input_digest"] != first["input_digest"]
    with db(app) as session:
        old = session.get(ContactPermission, uuid.UUID(permission))
        assert old is not None and (old.status, old.version) == ("superseded", 3)
        with pytest.raises(DBAPIError):  # the trigger refuses to resurrect superseded evidence
            session.execute(
                text("UPDATE contact_permissions SET status = 'verified', version = version + 1 WHERE id = :i"),
                {"i": permission},
            )
    new_id = edited.json()["permission_id"]
    assert review(owner[0], owner[1], contact, new_id).status_code == 201
    third = evaluate(client, operator, contact, **ask)
    assert third["decision"] == "allow_for_simulation" and third["permission_revision"] == {"id": new_id, "version": 2}
    assert revoke(client, operator, contact, new_id, 1).status_code == 409  # stale expected version
    assert revoke(client, operator, contact, new_id, 2).status_code == 201
    assert codes(evaluate(client, operator, contact, **ask)) == ["permission_revoked"]
    # Expiry: a fresh verified opt-in captured 10 days ago lapses after 365 days.
    again = record(client, operator, contact).json()["permission_id"]
    assert review(owner[0], owner[1], contact, again).status_code == 201
    clock.advance(timedelta(days=356))
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    late = evaluate(client, operator, contact)
    assert {"permission_expired", "proof_stale"} <= set(codes(late))


# --- ELIG-06 ----------------------------------------------------------------------------------------------------


def test_elig_06_inbound_service_window_is_24h_and_never_marketing_consent(
    app: FastAPI, client: TestClient, org: Org, operator: str, clock: FixedClock
) -> None:
    _campaign, account, _offer = approved(app, client, org, operator)
    contact = add_contact(client, operator, account).json()["id"]
    reply = {"purpose": "service_reply", "inbound_ref": "fx_inbound_hello_v1"}
    assert evaluate(client, operator, contact, **reply)["decision"] == "allow_for_simulation"  # 2h after "hello"
    marketing = evaluate(client, operator, contact, inbound_ref="fx_inbound_hello_v1", template_ref=TEMPLATE)
    assert "no_opt_in_permission" in codes(marketing)
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(ContactPermission)) == 0  # "hello" grants nothing
    other = add_contact(client, operator, account, "+92 000 0000105").json()["id"]
    assert codes(evaluate(client, operator, other, **reply)) == ["inbound_context_mismatch"]
    assert codes(evaluate(client, operator, contact, purpose="service_reply")) == ["no_inbound_context"]
    unknown = evaluate(client, operator, contact, purpose="service_reply", inbound_ref="fx_inbound_unknown")
    assert codes(unknown) == ["no_inbound_context"]
    forged = client.post(
        "/api/v1/channel-eligibility/evaluate",
        json={"contact_id": contact, "purpose": "service_reply", "last_inbound_at": FIXED_NOW.isoformat()},
        headers=mutation_headers(operator),
    )
    assert forged.status_code == 422  # a client never supplies an inbound time
    clock.advance(timedelta(hours=21, minutes=59, seconds=59))  # 23:59:59 after the inbound message
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert evaluate(client, operator, contact, **reply)["decision"] == "allow_for_simulation"
    clock.advance(timedelta(seconds=1))  # exactly 24h
    assert codes(evaluate(client, operator, contact, **reply)) == ["service_window_closed"]


# --- ELIG-07 ----------------------------------------------------------------------------------------------------


def test_elig_07_template_must_be_provider_approved_fixture_of_right_category(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, contact, _permission = verified_contact(app, client, org, operator, owner)
    cases = [
        (None, "template_missing"),
        ("fx_tpl_marketing_pending_v1", "template_unverified"),
        ("fx_tpl_marketing_rejected_v1", "template_rejected"),
        ("fx_tpl_utility_update_v1", "template_wrong_category"),
        ("fx_tpl_not_in_catalogue", "template_unverified"),
        ("operator_marked_approved", "template_unverified"),
    ]
    for ref, reason in cases:
        body: dict[str, Any] = {"campaign_id": campaign["id"]}
        if ref:
            body["template_ref"] = ref
        result = evaluate(client, operator, contact, **body)
        assert (result["decision"], codes(result)) == ("deny", [reason]), ref


# --- ELIG-08 ----------------------------------------------------------------------------------------------------


def test_elig_08_business_hours_in_asia_karachi_defer_without_queueing(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str], clock: FixedClock
) -> None:
    campaign, contact, _permission = verified_contact(app, client, org, operator, owner)
    before = counts(app)
    ask = {"campaign_id": campaign["id"], "template_ref": TEMPLATE}
    clock.advance(timedelta(hours=5, minutes=59, seconds=59))  # Friday 17:59:59 PKT
    assert evaluate(client, operator, contact, **ask)["decision"] == "allow_for_simulation"
    clock.advance(timedelta(seconds=1))  # Friday 18:00 PKT
    late = evaluate(client, operator, contact, **ask)
    assert (late["decision"], codes(late)) == ("defer", ["outside_business_hours"])
    assert late["next_window_at"] == "2026-10-24T04:00:00+00:00"  # Saturday 09:00 Asia/Karachi
    assert counts(app) == before  # a deferral queues nothing


# --- ELIG-09 ----------------------------------------------------------------------------------------------------


def test_elig_09_csrf_rbac_tenancy_evidence_attacks_and_masking(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    campaign, contact, permission = verified_contact(app, client, org, operator, owner)
    account = client.get(f"/api/v1/contacts/{contact}").json()["account_id"]
    url = "/api/v1/channel-eligibility/evaluate"
    assert client.post(url, json={"contact_id": contact, "purpose": "marketing"}).status_code == 403  # no CSRF
    assert (
        client.post(
            f"/api/v1/contacts/{contact}/suppress", json={"reason": "opt_out", "idempotency_key": key()}
        ).status_code
        == 403
    )
    attacks = [
        {"proof_reference": "FORM‮-0001"},
        {"proof_reference": "FORM\n0001"},
        {"business_name": "Coderz\u0000Hunt"},
        {"capture_method": "inferred_from_hello"},
        {"captured_at": "yesterday"},
    ]
    for attack in attacks:
        assert record(client, operator, contact, **attack).status_code == 422, attack
    assert add_contact(client, operator, account, "not a number").status_code == 422
    duplicate = add_contact(client, operator, account, "0092-000-000-0101")  # same number, other formatting
    assert duplicate.status_code == 409
    # Idempotent replay; same key with a different request is refused.
    body = evidence(purpose="utility", consent_wording_version="optin-whatsapp-utility-en-PK-v1")
    first = client.post(f"/api/v1/contacts/{contact}/permissions", json=body, headers=mutation_headers(operator))
    again = client.post(f"/api/v1/contacts/{contact}/permissions", json=body, headers=mutation_headers(operator))
    assert (first.status_code, again.status_code) == (201, 200) and again.json()["replayed"] is True
    assert first.json()["permission_id"] == again.json()["permission_id"]
    changed = body | {"proof_reference": "FORM-SYN-0099"}
    assert (
        client.post(
            f"/api/v1/contacts/{contact}/permissions", json=changed, headers=mutation_headers(operator)
        ).status_code
        == 409
    )
    # Observers read masked status only and cannot act.
    observer = TestClient(app, raise_server_exceptions=False)
    token = logged_in(observer, "observer@r.example")
    seen = observer.get(f"/api/v1/contacts/{contact}").json()
    assert seen["address"] == "+92 ••••••• 101"
    assert set(seen["permissions"][0]) == {"id", "purpose", "channel", "status", "version", "expires_at"}
    assert (
        observer.post(
            url, json={"contact_id": contact, "purpose": "marketing"}, headers=mutation_headers(token)
        ).status_code
        == 403
    )
    assert record(observer, token, contact).status_code == 403
    assert suppress(observer, token, contact).status_code == 403
    assert revoke(observer, token, contact, permission, 2).status_code == 403
    assert review(observer, token, contact, permission).status_code == 403
    # Another organization sees nothing.
    Org(app, "Other Org", "o")
    foreign = TestClient(app, raise_server_exceptions=False)
    other = logged_in(foreign, "operator@o.example")
    assert foreign.get(f"/api/v1/contacts/{contact}").status_code == 404
    assert foreign.get(f"/api/v1/accounts/{account}/contacts").status_code == 404
    assert (
        foreign.post(
            url, json={"contact_id": contact, "purpose": "marketing"}, headers=mutation_headers(other)
        ).status_code
        == 404
    )
    assert record(foreign, other, contact).status_code == 404
    assert suppress(foreign, other, contact).status_code == 404
    other_campaign = {"contact_id": contact, "purpose": "marketing", "campaign_id": campaign["id"]}
    assert foreign.post(url, json=other_campaign, headers=mutation_headers(other)).status_code == 404
    # Without configured contact keys, nothing can be stored (no built-in fallback key).
    settings = app.state.settings
    app.state.settings = settings.model_copy(update={"contact_hmac_secrets": None})
    try:
        assert add_contact(client, operator, account, "+92 000 0000188").status_code == 503
    finally:
        app.state.settings = settings
    client.cookies.clear()
    assert client.post(url, json={"contact_id": contact, "purpose": "marketing"}).status_code == 401
    # No plaintext number or proof reference is stored anywhere.
    with db(app) as session:
        dump = " ".join(
            str(row)
            for table in ("contacts", "contact_permissions", "suppression_entries", "contact_commands", "action_audits")
            for row in session.execute(text(f"SELECT * FROM {table}"))  # noqa: S608  # fixed table names
        )
    for secret in ("0000000101", "000 0000101", "FORM-SYN-0001", "FORM-SYN-0099"):
        assert secret not in dump, secret


# --- ELIG-10 ----------------------------------------------------------------------------------------------------


def test_elig_10_kill_switch_pause_exclusion_stale_state_and_zero_send_capability(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str], clock: FixedClock
) -> None:
    campaign, contact, _permission = verified_contact(app, client, org, operator, owner)
    before = counts(app)  # after setup (research enqueues its own jobs)
    ask = {"campaign_id": campaign["id"], "template_ref": TEMPLATE}
    settings = app.state.settings
    app.state.settings = settings.model_copy(update={"outreach_kill_switch": True})
    try:
        assert codes(evaluate(client, operator, contact, **ask)) == ["kill_switch_engaged"]
        reply = evaluate(client, operator, contact, purpose="service_reply", inbound_ref="fx_inbound_hello_v1")
        assert codes(reply) == ["kill_switch_engaged"]
    finally:
        app.state.settings = settings
    assert evaluate(client, operator, contact, **ask)["decision"] == "allow_for_simulation"
    clock.advance(timedelta(days=60))  # the cited research source's rights lapse: evidence changed
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert "evidence_changed" in codes(evaluate(client, operator, contact, **ask))
    clock.advance(timedelta(days=-60))
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert transition(client, operator, campaign["id"], "pause").status_code == 200
    assert "campaign_paused" in codes(evaluate(client, operator, contact, **ask))
    account = client.get(f"/api/v1/contacts/{contact}").json()["account_id"]
    exclude(client, operator, campaign["id"], account)
    assert {"campaign_paused", "excluded"} <= set(codes(evaluate(client, operator, contact, **ask)))
    # A live campaign is blocked by the closed evidence-quality gate.
    from tests.integration.test_campaigns import new_campaign  # noqa: PLC0415

    live = new_campaign(client, operator, uuid.UUID(campaign["offer_id"]), mode="live", name="Live pilot").json()
    gated = evaluate(client, operator, contact, campaign_id=live["id"], template_ref=TEMPLATE)
    assert {"evidence_quality_gate_closed", "not_approved_for_drafting"} <= set(codes(gated))
    # Zero send capability: no job type, table or outbox event for messaging.
    assert not [t for t, _v in registry.REGISTRY if any(w in t for w in ("send", "whatsapp", "message", "deliver"))]
    with db(app) as session:
        tables = set(session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))
    assert not {t for t in tables if any(w in t for w in ("message", "send", "outbound", "delivery"))}
    assert counts(app) == before


# --- Audit follow-ups (2026-10-25) --------------------------------------------------------------------------------


def test_audit_concurrent_duplicate_contacts_conflict_instead_of_500(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    _campaign, account, _offer = approved(app, client, org, operator)
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def add(number: str) -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        statuses.append(add_contact(local, token, account, number).status_code)

    threads = [threading.Thread(target=add, args=(n,)) for n in ("+92 000 0000177", "+92۰۰۰۰۰۰۰۱۷۷")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [201, 409]  # one number, whatever digits it was typed in


def test_audit_a_renamed_real_account_never_gets_fixture_trust(
    app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
) -> None:
    renamed = plain_account(app, org, "Real Lahore School (Synthetic)")  # name says synthetic; sources do not
    contact = add_contact(client, operator, renamed, "+92 000 0000178").json()["id"]
    permission = record(client, operator, contact).json()["permission_id"]
    assert review(owner[0], owner[1], contact, permission).status_code == 201
    blocked = evaluate(client, operator, contact, template_ref=TEMPLATE)
    assert "fixture_requires_synthetic_account_outside_production" in codes(blocked)
