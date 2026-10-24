"""P1.3 acceptance: OFFER-01..OFFER-10 over HTTP with real sessions, CSRF and Postgres."""

import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.models import Role, User
from app.core.clock import FixedClock
from app.core.settings import Settings
from app.offers import schemas
from app.offers.models import Offer, OfferRevision
from app.offers.seed import CODE, seed_school_admin_starter
from tests.integration.auth_helpers import add_organization, add_user, db, logged_in, mutation_headers
from tests.integration.db import API_ROOT

EVIDENCE = [
    {
        "ref": "internal-demo:fees-2026-10",
        "type": "internal-demo",
        "recorded_at": "2026-10-20T10:00:00Z",
        "description": "Fee tracking demoed against a reviewed build",
    },
    {
        "ref": "owner-review:admissions-2026-10",
        "type": "owner-review",
        "recorded_at": "2026-10-21T10:00:00Z",
        "description": "Owner reviewed admissions intake",
    },
]


def claim(code: str, readiness: str = "available", approved: bool = True, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "capability_code": code,
        "summary": f"{code.replace('_', ' ').title()} for school offices",
        "readiness": readiness,
        "approved_for_sales": approved,
    }
    if approved:
        body |= {"evidence_refs": ["internal-demo:fees-2026-10"], "approval_note": "Demoed against reviewed build"}
    return body | extra


def content(**overrides: Any) -> dict[str, Any]:
    return {
        "capability_version": "build-2026-10-20",
        "capability_matrix": [
            claim("fee_tracking"),
            claim(
                "admissions_intake",
                readiness="limited",
                limitations=["Manual import only"],
                evidence_refs=["owner-review:admissions-2026-10"],
            ),
            claim("parent_portal", readiness="planned", approved=False),
        ],
        "exclusions": ["Payroll is not included"],
        "dependencies": ["School provides a fee schedule spreadsheet"],
        "evidence_references": EVIDENCE,
        **overrides,
    }


@dataclass
class Team:
    app: FastAPI
    org: uuid.UUID
    clients: dict[Role, TestClient]
    csrf: dict[Role, str]
    user_ids: dict[Role, uuid.UUID]

    def post(self, role: Role, path: str, body: Any, **headers: str) -> Any:
        return self.clients[role].post(path, json=body, headers={**mutation_headers(self.csrf[role]), **headers})

    def get(self, role: Role, path: str) -> Any:
        return self.clients[role].get(path)

    def new_offer(self, code: str = "school_fees_pro", role: Role = Role.OWNER) -> dict[str, Any]:
        response = self.post(role, "/api/v1/offers", {"code": code, "audience": "Independent schools in Lahore"})
        assert response.status_code == 201, response.text
        return dict(response.json())

    def new_revision(self, offer: dict[str, Any], body: dict[str, Any] | None = None, role: Role = Role.OWNER) -> Any:
        version = self.get(Role.OWNER, f"/api/v1/offers/{offer['id']}").json()["version"]
        return self.post(
            role, f"/api/v1/offers/{offer['id']}/revisions", {"expected_version": version, "content": body or content()}
        )

    def publish(self, offer_id: str, revision: int, role: Role = Role.OWNER, version: int | None = None) -> Any:
        if version is None:
            version = self.get(Role.OWNER, f"/api/v1/offers/{offer_id}").json()["version"]
        return self.post(
            role, f"/api/v1/offers/{offer_id}/publish", {"revision": revision, "expected_version": version}
        )


@pytest.fixture
def team(app: FastAPI) -> Team:
    org = add_organization(app)
    clients, csrf, ids = {}, {}, {}
    for role in Role:
        email = f"{role.value}@offers.example"
        ids[role] = add_user(app, org, email, role=role)
        clients[role] = TestClient(app, raise_server_exceptions=False)
        csrf[role] = logged_in(clients[role], email)
    return Team(app, org, clients, csrf, ids)


def revision_rows(app: FastAPI) -> list[OfferRevision]:
    with db(app) as session:
        return list(session.scalars(select(OfferRevision).order_by(OfferRevision.revision)))


def offer_row(app: FastAPI, offer_id: str) -> Offer:
    with db(app) as session:
        offer = session.get(Offer, uuid.UUID(offer_id))
        assert offer is not None
        return offer


# --- OFFER-01 ------------------------------------------------------------------------------------


def test_seeded_school_draft_is_unpublished_with_no_claims_or_prices(team: Team, clock: FixedClock) -> None:
    with db(team.app) as session:
        owner = session.get(User, team.user_ids[Role.OWNER])
        assert owner is not None
        offer = seed_school_admin_starter(session, owner=owner, clock=clock)
        again = seed_school_admin_starter(session, owner=owner, clock=clock)
    assert again.id == offer.id
    listed = team.get(Role.OWNER, "/api/v1/offers").json()["offers"]
    assert [(o["code"], o["status"], o["published_revision"], o["current_draft_revision"]) for o in listed] == [
        (CODE, "draft", None, 1)
    ]
    detail = team.get(Role.OWNER, f"/api/v1/offers/{offer.id}").json()
    [revision] = detail["revisions"]
    assert {c["readiness"] for c in revision["capability_matrix"]} == {"unverified"}
    assert revision["approved_claims"] == [] and revision["price_rules"] == [] and revision["evidence_references"] == []
    sellable = team.get(Role.OWNER, f"/api/v1/offers/{offer.id}/sales-ready")
    assert (
        sellable.status_code == 409
        and sellable.json()["error"]["message"] == "Offer has no published, sellable revision"
    )
    published = team.publish(str(offer.id), 1)
    assert published.status_code == 400  # seeded draft cannot be published as-is


def test_seed_cli_needs_exactly_one_owner_and_never_publishes(app: FastAPI, app_settings: Settings) -> None:
    def run() -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DATABASE_URL": str(app_settings.database_url)}
        return subprocess.run(  # noqa: S603  # fixed argv
            [sys.executable, "-m", "app.offers.seed"],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    refused = run()
    assert refused.returncode == 1 and "expected exactly one active owner" in refused.stderr
    org = add_organization(app)
    add_user(app, org, "owner@seed.example")
    first, second = run(), run()
    assert first.returncode == second.returncode == 0
    assert "is draft" in second.stdout and "nothing was published" in second.stdout
    with db(app) as session:
        assert len(list(session.scalars(select(Offer)))) == 1
        assert all(r.state == "draft" for r in session.scalars(select(OfferRevision)))


# --- OFFER-02 ------------------------------------------------------------------------------------


def test_operator_drafts_but_cannot_publish(team: Team) -> None:
    offer = team.new_offer(role=Role.OPERATOR)
    created = team.new_revision(offer, role=Role.OPERATOR)
    assert created.status_code == 201 and created.json()["state"] == "draft"
    denied = team.publish(offer["id"], 1, role=Role.OPERATOR)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    assert offer_row(team.app, offer["id"]).status == "draft"
    assert [r.state for r in revision_rows(team.app)] == ["draft"]


def test_observer_is_read_only_and_never_sees_drafts(team: Team) -> None:
    assert team.post(Role.OBSERVER, "/api/v1/offers", {"code": "observer_offer", "audience": "x"}).status_code == 403
    offer = team.new_offer()
    team.new_revision(offer)
    assert team.get(Role.OBSERVER, f"/api/v1/offers/{offer['id']}").json()["revisions"] == []
    assert team.publish(offer["id"], 1, role=Role.OBSERVER).status_code == 403


# --- OFFER-03 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("readiness", ["planned", "unverified", "not_supported"])
def test_unsellable_readiness_in_approved_claims_blocks_publication(team: Team, readiness: str) -> None:
    offer = team.new_offer()
    body = content(capability_matrix=[claim("fee_tracking"), claim("ai_timetable", readiness=readiness)])
    assert team.new_revision(offer, body).status_code == 201
    before = offer_row(team.app, offer["id"])
    refused = team.publish(offer["id"], 1)
    assert refused.status_code == 400
    assert refused.json()["error"]["message"] == (
        f"claim ai_timetable has readiness {readiness}; only available or limited can sell"
    )
    after = offer_row(team.app, offer["id"])
    assert (after.status, after.version, after.published_revision_id) == ("draft", before.version, None)
    assert [(r.state, r.approved_by) for r in revision_rows(team.app)] == [("draft", None)]


@pytest.mark.parametrize(
    ("bad_claim", "message"),
    [
        (claim("fee_tracking", evidence_refs=[]), "has no evidence reference"),
        (claim("fee_tracking", approval_note=None), "has no approval note"),
        (claim("fee_tracking", readiness="limited"), "is limited but lists no limitations"),
    ],
    ids=["no-evidence", "no-approval-note", "limited-without-limitations"],
)
def test_unsubstantiated_claims_block_publication(team: Team, bad_claim: dict[str, Any], message: str) -> None:
    offer = team.new_offer()
    assert team.new_revision(offer, content(capability_matrix=[bad_claim])).status_code == 201
    refused = team.publish(offer["id"], 1)
    assert refused.status_code == 400 and message in refused.json()["error"]["message"]
    assert offer_row(team.app, offer["id"]).published_revision_id is None


# --- OFFER-04 ------------------------------------------------------------------------------------


def test_valid_revision_publishes_one_atomic_snapshot(team: Team) -> None:
    offer = team.new_offer()
    created = team.new_revision(offer).json()
    published = team.publish(offer["id"], 1)
    assert published.status_code == 200
    body = published.json()
    assert body["state"] == "published"
    assert body["approved_by"] == str(team.user_ids[Role.OWNER])
    assert body["approved_at"] == body["published_at"] is not None
    assert body["content_sha256"] == created["content_sha256"]
    assert body["content_sha256"] == schemas.RevisionContent.model_validate(content()).digest()

    sellable = team.get(Role.OBSERVER, f"/api/v1/offers/{offer['id']}/sales-ready").json()
    assert sellable["revision"] == 1 and sellable["content_sha256"] == body["content_sha256"]
    assert [c["capability_code"] for c in sellable["claims"]] == ["fee_tracking", "admissions_intake"]
    assert sellable["claims"][1]["limitations"] == ["Manual import only"]
    assert "parent_portal" not in json.dumps(sellable)  # planned capability stays internal
    assert sellable["exclusions"] == ["Payroll is not included"]
    assert sellable["pricing"] == {"status": "pricing_unavailable"}
    row = offer_row(team.app, offer["id"])
    assert (row.status, row.current_draft_revision_id) == ("published", None)


# --- OFFER-05 ------------------------------------------------------------------------------------


def test_published_snapshot_is_immutable_and_new_drafts_do_not_replace_it(team: Team, app_settings: Settings) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    digest = team.publish(offer["id"], 1).json()["content_sha256"]
    changed = content(capability_matrix=[claim("fee_tracking", summary="Fee tracking v2 for school offices")])
    assert team.new_revision(offer, changed).status_code == 201
    sellable = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}/sales-ready").json()
    assert sellable["revision"] == 1 and sellable["content_sha256"] == digest

    published_id = revision_rows(team.app)[0].id
    attacks = [
        "UPDATE offer_revisions SET approved_claims_json = '[]' WHERE id = %(id)s",
        "UPDATE offer_revisions SET content_sha256 = repeat('0', 64) WHERE id = %(id)s",
        "UPDATE offer_revisions SET state = 'draft' WHERE id = %(id)s",
        "UPDATE offer_revisions SET approved_at = now() WHERE id = %(id)s",
        "DELETE FROM offer_revisions WHERE id = %(id)s",
    ]
    for sql in attacks:
        with (
            psycopg.connect(str(app_settings.database_url), autocommit=True) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            conn.execute(sql, {"id": published_id})
    with db(team.app) as session:
        revision = session.get(OfferRevision, published_id)
        assert revision is not None
        revision.price_rules_json = [{"code": "sneaky"}]
        with pytest.raises(Exception, match="immutable"):
            session.commit()
    after = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}/sales-ready").json()
    assert after["content_sha256"] == digest and after["pricing"] == {"status": "pricing_unavailable"}


# --- OFFER-06 ------------------------------------------------------------------------------------


def test_concurrent_publishers_with_the_same_version_one_wins(team: Team) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    version = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}").json()["version"]
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait()
        statuses.append(team.publish(offer["id"], 1, version=version).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200, 409]
    row = offer_row(team.app, offer["id"])
    published = [r for r in revision_rows(team.app) if r.state == "published"]
    assert len(published) == 1 and row.published_revision_id == published[0].id


def test_stale_writers_get_409(team: Team) -> None:
    offer = team.new_offer()
    stale = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}").json()["version"]
    team.new_revision(offer)
    late = team.post(
        Role.OPERATOR, f"/api/v1/offers/{offer['id']}/revisions", {"expected_version": stale, "content": content()}
    )
    assert late.status_code == 409 and "reload and retry" in late.json()["error"]["message"]
    assert team.publish(offer["id"], 1, version=stale).status_code == 409
    assert len(revision_rows(team.app)) == 1


def test_publish_racing_archive_leaves_a_consistent_state(team: Team) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    version = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}").json()["version"]
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def do_publish() -> None:
        barrier.wait()
        results["publish"] = team.publish(offer["id"], 1, version=version).status_code

    def do_archive() -> None:
        barrier.wait()
        results["archive"] = team.post(
            Role.OWNER, f"/api/v1/offers/{offer['id']}/archive", {"expected_version": version}
        ).status_code

    threads = [threading.Thread(target=do_publish), threading.Thread(target=do_archive)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()) == [200, 409]
    row = offer_row(team.app, offer["id"])
    states = [r.state for r in revision_rows(team.app)]
    if results["publish"] == 200:
        assert row.status == "published" and states == ["published"]
    else:
        assert row.status == "archived" and states == ["retired"]


# --- OFFER-07 ------------------------------------------------------------------------------------


def test_archive_withdraws_selling_but_keeps_history(team: Team) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    team.publish(offer["id"], 1)
    version = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}").json()["version"]
    archived = team.post(Role.OWNER, f"/api/v1/offers/{offer['id']}/archive", {"expected_version": version})
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}/sales-ready").status_code == 409
    history = team.get(Role.OBSERVER, f"/api/v1/offers/{offer['id']}").json()["revisions"]
    assert [(r["revision"], r["state"], r["published_at"] is not None) for r in history] == [(1, "retired", True)]
    assert team.new_revision(offer).status_code == 409
    assert team.publish(offer["id"], 1).status_code == 409


# --- OFFER-08 ------------------------------------------------------------------------------------


def test_other_organizations_cannot_see_or_touch_offers(team: Team, app_settings: Settings) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    team.publish(offer["id"], 1)
    other_org = add_organization(team.app, "Other Org")
    add_user(team.app, other_org, "intruder@other.example")
    intruder = TestClient(team.app, raise_server_exceptions=False)
    csrf = logged_in(intruder, "intruder@other.example")
    assert intruder.get("/api/v1/offers").json() == {"offers": []}
    for path in (f"/api/v1/offers/{offer['id']}", f"/api/v1/offers/{offer['id']}/sales-ready"):
        response = intruder.get(path)
        assert response.status_code == 404 and offer["code"] not in response.text
    publish = intruder.post(
        f"/api/v1/offers/{offer['id']}/archive", json={"expected_version": 99}, headers=mutation_headers(csrf)
    )
    assert publish.status_code == 404
    with (
        psycopg.connect(str(app_settings.database_url), autocommit=True) as conn,
        pytest.raises(psycopg.errors.ForeignKeyViolation, match="fk_offer_revisions_org_offer"),
    ):
        conn.execute(
            "INSERT INTO offer_revisions (id, organization_id, offer_id, revision, state, capability_version,"
            " approved_claims_json, capability_matrix_json, price_rules_json, exclusions_json, dependencies_json,"
            " evidence_references_json, created_by, content_sha256, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, %(offer)s, 9, 'draft', 'x', '[]', '[]', '[]', '[]', '[]', '[]',"
            " %(user)s, repeat('a', 64), now())",
            {"org": other_org, "offer": offer["id"], "user": team.user_ids[Role.OWNER]},
        )


# --- OFFER-09 ------------------------------------------------------------------------------------


def price(**extra: Any) -> dict[str, Any]:
    return {
        "code": "per_student",
        "description": "Monthly fee per enrolled student",
        "currency": "PKR",
        "amount": "150.00",
        "unit": "per_student_month",
        **extra,
    }


def test_pricing_must_be_approved_with_evidence(team: Team) -> None:
    offer = team.new_offer()
    team.new_revision(offer, content(price_rules=[price()]))
    refused = team.publish(offer["id"], 1)
    assert refused.status_code == 400 and "price rule per_student is not approved" in refused.json()["error"]["message"]
    team.new_revision(offer, content(price_rules=[price(approved=True, evidence_ref="internal-demo:fees-2026-10")]))
    assert team.publish(offer["id"], 2).status_code == 200
    pricing = team.get(Role.OWNER, f"/api/v1/offers/{offer['id']}/sales-ready").json()["pricing"]
    assert pricing == {
        "status": "approved",
        "rules": [
            {
                "code": "per_student",
                "description": "Monthly fee per enrolled student",
                "currency": "PKR",
                "amount": "150.00",
                "unit": "per_student_month",
            }
        ],
    }


@pytest.mark.parametrize(
    "rule",
    [price(amount="-5.00"), price(amount="0"), price(amount="1.999"), price(currency="USD"), price(unit="per_click")],
    ids=["negative", "zero", "three-decimals", "currency", "unit"],
)
def test_invalid_price_rules_are_rejected_at_draft_time(team: Team, rule: dict[str, Any]) -> None:
    offer = team.new_offer()
    response = team.new_revision(offer, content(price_rules=[rule]))
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert revision_rows(team.app) == []


@pytest.mark.parametrize(
    "summary",
    [
        "Guaranteed go-live within 2 weeks",
        "Delivered in 10 days",
        "99.9% uptime SLA",
        "Integrates with Odoo and QuickBooks",
    ],
)
def test_invented_commitments_cannot_be_published(team: Team, summary: str) -> None:
    offer = team.new_offer()
    team.new_revision(offer, content(capability_matrix=[claim("fee_tracking", summary=summary)]))
    refused = team.publish(offer["id"], 1)
    assert refused.status_code == 400 and "commitment" in refused.json()["error"]["message"]


# --- OFFER-10 ------------------------------------------------------------------------------------


def test_csrf_anonymous_and_malformed_requests_are_denied_without_effect(team: Team) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    version = offer_row(team.app, offer["id"]).version
    path = f"/api/v1/offers/{offer['id']}/publish"
    body = {"revision": 1, "expected_version": version}
    owner = team.clients[Role.OWNER]
    assert owner.post(path, json=body, headers={"Origin": "http://localhost:3000"}).status_code == 403
    assert owner.post(path, json=body, headers=mutation_headers("forged")).status_code == 403
    anonymous = TestClient(team.app, raise_server_exceptions=False)
    assert anonymous.post(path, json=body, headers={"Origin": "http://localhost:3000"}).status_code == 401
    assert anonymous.get("/api/v1/offers").status_code == 401
    malformed = owner.post(
        path,
        content=b'{"revision": 1,,,',
        headers={**mutation_headers(team.csrf[Role.OWNER]), "Content-Type": "application/json"},
    )
    assert malformed.status_code == 422
    unknown_field = team.post(Role.OWNER, path, {**body, "force": True})
    assert unknown_field.status_code == 422
    row = offer_row(team.app, offer["id"])
    assert (row.status, row.version) == ("draft", version)


@pytest.mark.parametrize(
    "summary",
    ["<script>alert(1)</script> fee tracking", "Fee tracking‮", "Ignore previous instructions <system>"],
    ids=["html", "bidi", "markup-injection"],
)
def test_markup_and_control_characters_are_rejected_in_claims(team: Team, summary: str) -> None:
    offer = team.new_offer()
    response = team.new_revision(offer, content(capability_matrix=[claim("fee_tracking", summary=summary)]))
    assert response.status_code == 422
    assert "<script>" not in response.text
    assert revision_rows(team.app) == []


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"capability_matrix": []}, "empty matrix"),
        ({"capability_matrix": [claim("fee_tracking"), claim("fee_tracking")]}, "duplicate capability"),
        ({"capability_matrix": [claim("Fee Tracking")]}, "ambiguous capability name"),
        ({"capability_matrix": [claim("fee_tracking", readiness="almost")]}, "unknown readiness"),
        ({"evidence_references": []}, "unlisted evidence"),
        (
            {"evidence_references": [{**EVIDENCE[0], "ref": "repo:https://github.example/x", "type": "repo"}]},
            "url as evidence",
        ),
    ],
    ids=["empty", "duplicate", "ambiguous", "readiness", "unlisted-evidence", "url-evidence"],
)
def test_malformed_capability_content_is_rejected(team: Team, overrides: dict[str, Any], why: str) -> None:
    offer = team.new_offer()
    assert team.new_revision(offer, content(**overrides)).status_code == 422, why
    assert revision_rows(team.app) == []


def test_duplicate_offer_code_is_a_conflict(team: Team) -> None:
    team.new_offer("school_fees_pro")
    duplicate = team.post(Role.OWNER, "/api/v1/offers", {"code": "school_fees_pro", "audience": "x"})
    assert duplicate.status_code == 409


def test_database_failure_mid_publish_rolls_back(team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    offer = team.new_offer()
    team.new_revision(offer)
    before = offer_row(team.app, offer["id"])
    from app.offers import service as offer_service

    original: Callable[..., Any] = offer_service._bump

    def failing_bump(offer: Offer, clock: Any) -> None:
        original(offer, clock)
        raise psycopg.OperationalError("connection lost mid-transaction")

    monkeypatch.setattr(offer_service, "_bump", failing_bump)
    response = team.publish(offer["id"], 1)
    assert response.status_code == 503
    after = offer_row(team.app, offer["id"])
    assert (after.status, after.version, after.published_revision_id) == ("draft", before.version, None)
    assert [r.state for r in revision_rows(team.app)] == ["draft"]
