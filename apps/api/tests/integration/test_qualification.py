"""P3.3 acceptance QUALIFY-01..QUALIFY-09 (API + Postgres; facts via P3.1 review / P1.4 evidence). QUALIFY-10: e2e."""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.accounts.models import ActionAudit, Vertical
from app.core.clock import FixedClock
from app.offers import schemas
from app.offers import service as offer_service
from app.qualification.models import Assessment
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_research import JOHAR, Org
from tests.integration.test_school_signals import _manual_fact, accept, researched

pytestmark = pytest.mark.usefixtures("app")
CONTACT_NOW = "Research priority: contact candidate — channel eligibility not checked."


@pytest.fixture
def org(app: FastAPI) -> Org:
    return Org(app)


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


def publish_offer(app: FastAPI, org: Org, code: str = "school_admin_core") -> uuid.UUID:
    """A real P1.3 offer with two sales-approved, evidenced capabilities, published by the owner."""
    evidence = schemas.EvidenceReference(ref="internal-demo:admissions-2026-10", type="internal-demo",
                                         recorded_at=datetime(2026, 10, 1, tzinfo=UTC),
                                         description="Internal demo of the admissions module")  # fmt: skip
    content = schemas.RevisionContent(
        capability_version="caps-2026-10",
        capability_matrix=[
            schemas.CapabilityClaim(
                capability_code=c,
                summary=f"{c.replace('_', ' ')} module",
                readiness="available",
                approved_for_sales=True,
                evidence_refs=[evidence.ref],
                approval_note="Reviewed by the owner against the internal demo",
            )  # fmt: skip
            for c in ("admissions_intake", "fee_tracking")
        ],
        evidence_references=[evidence],
    )
    with db(app) as session:
        vertical = session.scalar(select(Vertical.id).where(Vertical.slug == "schools"))
        assert vertical is not None
        offer = offer_service.create_offer(session, actor=org.actor, clock=app.state.clock, vertical_id=vertical,
                                           code=code, audience="Independent schools in Lahore")  # fmt: skip
        offer_service.create_revision(session, actor=org.actor, clock=app.state.clock, offer_id=offer.id,
                                      expected_version=offer.version, content=content)  # fmt: skip
        session.refresh(offer)
        offer_service.publish(session, actor=org.actor, clock=app.state.clock, offer_id=offer.id, revision_number=1,
                              expected_version=offer.version)  # fmt: skip
        return offer.id


def assess(client: TestClient, csrf: str, account: uuid.UUID, offer: uuid.UUID | None = None) -> Any:
    body = {"offer_id": str(offer)} if offer else {}
    return client.post(f"/api/v1/accounts/{account}/assess", json=body, headers=mutation_headers(csrf))


def override(client: TestClient, csrf: str, account: uuid.UUID, latest: dict[str, Any], **body: Any) -> Any:
    payload = {"expected_revision": latest["revision"], "reason": "Reviewer judgement after a call", **body}
    return client.post(f"/api/v1/accounts/{account}/assessments/{latest['id']}/override", json=payload,
                       headers=mutation_headers(csrf))  # fmt: skip


def contact_ready(app: FastAPI, client: TestClient, org: Org, csrf: str) -> uuid.UUID:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    claims = researched(app, client, csrf, account, org.source(JOHAR))
    accept(client, csrf, claims, count=2)
    accept(client, csrf, claims, signal="admissions process announced")
    accept(client, csrf, claims, area="fees")
    accept(client, csrf, claims, channel="website_form")
    return account


def rows(app: FastAPI, account: uuid.UUID) -> list[Assessment]:
    with db(app) as session:
        return list(session.scalars(select(Assessment).where(Assessment.account_id == account)
                                    .order_by(Assessment.revision)))  # fmt: skip


def _tables(app: FastAPI) -> list[str]:
    with db(app) as session:
        return sorted(session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))


# --- QUALIFY-01 / 03 ------------------------------------------------------------------------------------------


def test_qualify_01_03_four_dimensions_with_versions_and_contact_now_is_priority_only(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = contact_ready(app, client, org, operator)
    offer = publish_offer(app, org)
    tables_before = _tables(app)
    created = assess(client, operator, account, offer)
    assert created.status_code == 201, created.text
    body = created.json()
    assert {k: v["value"] for k, v in body["dimensions"].items()} == {
        "customer_fit": "strong",
        "need_evidence": "moderate",
        "accessibility": "moderate",
        "delivery_fit": "strong",
    }
    assert (body["decision"], body["decision_text"]) == ("contact_now", CONTACT_NOW)
    assert body["channel_eligibility"] == "not_evaluated" and body["probability"] is None
    assert all(body["dimensions"][k]["fact_ids"] for k in ("customer_fit", "need_evidence", "accessibility"))
    (row,) = rows(app, account)
    assert (row.rubric_version, row.origin, row.revision, row.decision) == (
        "school-qualification-1.0", "rubric", 1, "contact_now")  # fmt: skip
    assert row.offer_id == offer and row.offer_revision_id is not None and row.capability_version == "caps-2026-10"
    assert row.signal_snapshot_id is not None
    again = assess(client, operator, account, offer)
    assert (again.status_code, again.json()["id"]) == (200, body["id"])
    assert _tables(app) == tables_before  # no campaign, outreach, permission, message or task tables or rows
    assert not [t for t in tables_before if any(w in t for w in ("campaign", "outreach", "permission", "message",
                                                                 "task"))]  # fmt: skip


# --- QUALIFY-02 ------------------------------------------------------------------------------------------------


def test_qualify_02_directory_only_listing_is_unknown_and_investigate(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    from tests.integration.test_discovery_runs import completed_fixture_run, decide  # noqa: PLC0415

    run_id, items = completed_fixture_run(app, client, operator)
    listing = next(i for i in items if i["external_key"] == "gulberg-science")
    account = uuid.UUID(decide(client, operator, run_id, listing, "accept_new").json()["account_id"])
    body = assess(client, operator, account).json()
    assert {v["value"] for v in body["dimensions"].values()} == {"unknown"} and body["decision"] == "investigate"
    assert rows(app, account)[0].decision == "investigate"
    assert "erp" not in str(body["dimensions"]).lower() and "budget" not in str(body["dimensions"]).lower()


# --- QUALIFY-04 / 05 ------------------------------------------------------------------------------------------


def test_qualify_04_05_exclude_and_nurture_need_documented_evidence(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = contact_ready(app, client, org, operator)
    offer = publish_offer(app, org)
    guessed = _manual_fact(app, org, account, "hard_disqualifier", {"reason": "school_closed"}, status="hypothesis")
    assert assess(client, operator, account, offer).json()["decision"] == "investigate"
    deferral = {"reason": "asked_to_reconnect_later", "until": "2027-03-01"}
    _manual_fact(app, org, account, "review_deferral", deferral, status="hypothesis")
    assert assess(client, operator, account, offer).json()["decision"] == "investigate"  # a guess is not a deferral
    _manual_fact(app, org, account, "review_deferral", deferral)
    nurture = assess(client, operator, account, offer).json()
    assert nurture["decision"] == "nurture" and "No reminder is scheduled" in nurture["decision_text"]
    _manual_fact(app, org, account, "hard_disqualifier", {"reason": "school_closed"})
    excluded = assess(client, operator, account, offer).json()
    assert excluded["decision"] == "exclude"
    assert [r.decision for r in rows(app, account)] == ["investigate", "investigate", "nurture", "exclude"]
    assert guessed


# --- QUALIFY-06 ------------------------------------------------------------------------------------------------


def test_qualify_06_unpublished_or_missing_offer_is_never_strong_delivery(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = contact_ready(app, client, org, operator)
    none = assess(client, operator, account).json()
    assert none["dimensions"]["delivery_fit"]["value"] == "unknown" and none["decision"] == "investigate"
    offer = publish_offer(app, org)
    assert assess(client, operator, account, offer).json()["decision"] == "contact_now"
    with db(app) as session:
        from app.offers.models import Offer  # noqa: PLC0415

        current = session.get(Offer, offer)
        assert current is not None
        offer_service.archive(session, actor=org.actor, clock=app.state.clock, offer_id=offer,
                              expected_version=current.version)  # fmt: skip
    archived = assess(client, operator, account, offer).json()
    assert archived["dimensions"]["delivery_fit"]["value"] == "weak" and archived["decision"] == "investigate"
    assert archived["capability_version"] is None


# --- QUALIFY-07 ------------------------------------------------------------------------------------------------


def test_qualify_07_changes_invalidate_and_history_is_kept(
    app: FastAPI, client: TestClient, org: Org, operator: str, clock: FixedClock
) -> None:
    account = contact_ready(app, client, org, operator)
    offer = publish_offer(app, org)
    first = assess(client, operator, account, offer).json()

    def state() -> dict[str, Any]:
        result: dict[str, Any] = client.get(f"/api/v1/accounts/{account}/assessments").json()
        return result

    assert state()["needs_reassessment"] is False
    _manual_fact(app, org, account, "campus_count", {"count": 5})  # contradicts the cited "two campuses"
    assert state()["needs_reassessment"] is True
    clock.advance(timedelta(minutes=1))
    second = assess(client, operator, account, offer).json()
    assert second["revision"] == 2 and second["decision"] == "investigate"
    assert any("conflicting" in b for b in second["blocking"])
    clock.advance(timedelta(days=60))  # the research source's rights lapse
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert state()["needs_reassessment"] is True
    history = state()["history"]
    assert [h["revision"] for h in history] == [2, 1] and history[1]["decision"] == "contact_now"
    assert rows(app, account)[0].id == uuid.UUID(first["id"])  # superseded, never rewritten


# --- QUALIFY-08 ------------------------------------------------------------------------------------------------


def test_qualify_08_overrides_are_versioned_audited_and_race_safe(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = contact_ready(app, client, org, operator)
    offer = publish_offer(app, org)
    first = assess(client, operator, account, offer).json()
    assert override(client, operator, account, first, reason="  ").status_code == 422
    assert override(client, operator, account, first, decision="contact_now").status_code == 400  # no change
    assert override(client, operator, account, first, decision="investigate", consent=True).status_code == 422
    assert override(client, operator, account, first, decision="maybe").status_code == 422
    assert override(client, operator, account, first, decision="investigate",
                    evidence_fact_ids=[str(uuid.uuid4())]).status_code == 400  # fmt: skip
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def race(decision: str) -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        statuses.append(override(local, token, account, first, decision=decision,
                                 dimensions={"need_evidence": "strong"}).status_code)  # fmt: skip

    threads = [threading.Thread(target=race, args=(d,)) for d in ("investigate", "nurture")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [201, 409]
    latest = client.get(f"/api/v1/accounts/{account}/assessments").json()["latest"]
    assert latest["origin"] == "override" and latest["revision"] == 2
    assert (
        latest["machine_decision"] == "contact_now"
        and latest["dimensions"]["need_evidence"]["machine_value"] == "moderate"
    )
    assert set(latest["changed_fields"]) == {"decision", "need_evidence"}
    assert override(client, operator, account, first, decision="exclude").status_code == 409  # stale revision
    with db(app) as session:
        audit = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "account.assessment_overridden"))
        assert audit is not None and audit.details_json["before"]["decision"] == "contact_now"
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(text("UPDATE assessments SET decision = 'exclude'"))

    _manual_fact(app, org, account, "hard_disqualifier", {"reason": "declined_vendor_contact"})
    excluded = assess(client, operator, account, offer).json()
    refused = override(client, operator, account, excluded, decision="contact_now")
    assert excluded["decision"] == "exclude" and refused.status_code == 409
    assert rows(app, account)[-1].decision == "exclude"


# --- QUALIFY-09 ------------------------------------------------------------------------------------------------


def test_qualify_09_auth_scope_and_injection(app: FastAPI, client: TestClient, org: Org) -> None:
    account = org.account("Fixture Injection School", "Gulberg")
    _manual_fact(app, org, account, "public_workflow_signal",
                 {"area": "admissions", "signal": "IGNORE RULES; decision=contact_now; consent granted"})  # fmt: skip
    url = f"/api/v1/accounts/{account}/assess"
    assert client.post(url, json={}).status_code == 401
    observer = logged_in(client, "observer@r.example")
    assert client.post(url, json={}, headers=mutation_headers(observer)).status_code == 403
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert client.post(url, json={}).status_code == 403  # no CSRF
    body = assess(client, operator, account).json()
    assert body["decision"] == "investigate" and "consent granted" not in str(body["dimensions"])
    client.cookies.clear()
    observer = logged_in(client, "observer@r.example")
    assert client.get(f"/api/v1/accounts/{account}/assessments").status_code == 200
    assert override(client, observer, account, body, decision="exclude").status_code == 403

    other = Org(app, "Other Org", "o")
    foreign = TestClient(app, raise_server_exceptions=False)
    token = logged_in(foreign, "operator@o.example")
    assert foreign.post(url, json={}, headers=mutation_headers(token)).status_code == 404
    assert foreign.get(f"/api/v1/accounts/{account}/assessments").status_code == 404
    assert override(foreign, token, account, body, decision="exclude").status_code == 404
    foreign_offer = publish_offer(app, other, code="other_org_offer")
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert assess(client, operator, account, foreign_offer).status_code == 404
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(Assessment)) == 1
