"""P4.1 acceptance CAMPAIGN-01..09 (API + Postgres). CAMPAIGN-10 is e2e. Nothing here is a contact action."""

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.accounts import management
from app.accounts.models import ActionAudit, Vertical
from app.campaigns import rules as campaign_rules
from app.campaigns import service as campaign_service
from app.campaigns.models import Campaign, CampaignAccount, CampaignDailyUsage
from app.core.clock import FixedClock
from app.jobs.models import OutboxEvent
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_evaluation import Team, judge
from tests.integration.test_evaluation import create as create_eval
from tests.integration.test_evaluation import detail as eval_detail
from tests.integration.test_evaluation import finalize as finalize_eval
from tests.integration.test_qualification import assess, contact_ready, publish_offer
from tests.integration.test_research import Org

pytestmark = pytest.mark.usefixtures("app")
NOTICE = "Channel permission not checked — do not contact from this screen."


@pytest.fixture
def org(app: FastAPI) -> Org:
    return Org(app)


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


def key() -> str:
    return f"cmp-{uuid.uuid4().hex[:16]}"


def new_campaign(client: TestClient, csrf: str, offer: uuid.UUID, mode: str = "fixture", **extra: Any) -> Any:
    body = {"name": "Lahore schools pilot", "offer_id": str(offer), "mode": mode, **extra}
    return client.post("/api/v1/campaigns", json=body, headers=mutation_headers(csrf))


def preview(client: TestClient, campaign_id: str, **params: Any) -> dict[str, Any]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    body: dict[str, Any] = client.get(f"/api/v1/campaigns/{campaign_id}/preview?{query}").json()
    return body


def item(view: dict[str, Any], account: uuid.UUID) -> dict[str, Any]:
    found: dict[str, Any] = next(i for i in view["items"] if i["account_id"] == str(account))
    return found


def approve(
    client: TestClient, csrf: str, campaign: dict[str, Any], row: dict[str, Any], idem: str | None = None
) -> Any:
    body = {
        "expected_revision": campaign["revision"],
        "item_digest": row["item_digest"],
        "idempotency_key": idem or key(),
    }
    return client.post(
        f"/api/v1/campaigns/{campaign['id']}/candidates/{row['account_id']}/approve",
        json=body,
        headers=mutation_headers(csrf),
    )


def exclude(client: TestClient, csrf: str, campaign_id: str, account: Any, idem: str | None = None) -> Any:
    body = {"reason": "Owner asked us not to pursue", "idempotency_key": idem or key()}
    return client.post(
        f"/api/v1/campaigns/{campaign_id}/candidates/{account}/exclude", json=body, headers=mutation_headers(csrf)
    )


def transition(client: TestClient, csrf: str, campaign_id: str, action: str) -> Any:
    revision = client.get(f"/api/v1/campaigns/{campaign_id}").json()["revision"]
    return client.post(
        f"/api/v1/campaigns/{campaign_id}/{action}",
        json={"expected_revision": revision},
        headers=mutation_headers(csrf),
    )


def ready(app: FastAPI, client: TestClient, org: Org, csrf: str) -> tuple[uuid.UUID, uuid.UUID]:
    account = contact_ready(app, client, org, csrf)
    offer = publish_offer(app, org)
    assert assess(client, csrf, account, offer).json()["decision"] == "contact_now"
    return account, offer


def count(app: FastAPI, model: type[Any]) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def plain_account(app: FastAPI, org: Org, name: str, city: str = "Lahore") -> uuid.UUID:
    with db(app) as session:
        vertical = session.scalar(select(Vertical.id).where(Vertical.slug == "schools"))
        assert vertical is not None
        return management.create(
            session,
            actor=org.actor,
            clock=app.state.clock,
            vertical_id=vertical,
            name=name,
            city=city,
            locality="Gulberg",
        ).id


# --- CAMPAIGN-01 ----------------------------------------------------------------------------------------------


def test_campaign_01_draft_campaign_pins_the_published_offer_and_is_audited(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    offer = publish_offer(app, org)
    created = new_campaign(client, operator, offer, mode="live")
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["status"], body["mode"], body["revision"], body["city"]) == ("draft", "live", 1, "Lahore")
    assert body["capability_version"] == "caps-2026-10" and body["offer_current"] is True
    assert body["notice"] == NOTICE and body["contact_authorized"] is False
    assert body["rules"]["decisions"] == ["contact_now"] and body["rules_version"] == "campaign-rules-1.0"
    with db(app) as session:
        audit = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "campaign.created"))
        assert audit is not None and audit.details_json["offer_revision_id"] == body["offer_revision_id"]
    unpublished = org_offer_draft(app, org)
    assert new_campaign(client, operator, unpublished).status_code == 409


def org_offer_draft(app: FastAPI, org: Org) -> uuid.UUID:
    from app.offers import service as offer_service  # noqa: PLC0415

    with db(app) as session:
        vertical = session.scalar(select(Vertical.id).where(Vertical.slug == "schools"))
        assert vertical is not None
        return offer_service.create_offer(
            session,
            actor=org.actor,
            clock=app.state.clock,
            vertical_id=vertical,
            code="draft_only_offer",
            audience="Draft",
        ).id


# --- CAMPAIGN-02 / 03 --------------------------------------------------------------------------------------------


def test_campaign_02_03_preview_reasons_typed_rules_and_stable_pages(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar, offer = ready(app, client, org, operator)
    unassessed = plain_account(app, org, "Unassessed Fixture School (Synthetic)")
    karachi = plain_account(app, org, "Karachi Fixture School (Synthetic)", city="Karachi")
    excluded = plain_account(app, org, "Excluded Fixture School (Synthetic)")
    campaign = new_campaign(client, operator, offer).json()
    exclude(client, operator, campaign["id"], excluded)
    view = preview(client, campaign["id"])
    assert view["notice"] == NOTICE and view["mode"] == "fixture"
    assert item(view, johar)["qualifies"] is True and item(view, johar)["decision"] == "contact_now"
    assert "unassessed" in item(view, unassessed)["reasons"]
    assert "other_city" in item(view, karachi)["reasons"]
    assert "manually_excluded" in item(view, excluded)["reasons"]
    assert view["items"][0]["account_id"] == str(johar)  # qualifying first, deterministic order
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(CampaignAccount)) == 1  # preview wrote nothing
    first = preview(client, campaign["id"], limit=2)
    second = preview(client, campaign["id"], limit=2, cursor=2, digest=first["preview_digest"])
    assert first["preview_digest"] == second["preview_digest"] and first["next_cursor"] == 2
    assert {i["account_id"] for i in first["items"]}.isdisjoint({i["account_id"] for i in second["items"]})
    plain_account(app, org, "Late Fixture School (Synthetic)")
    stale = client.get(f"/api/v1/campaigns/{campaign['id']}/preview?limit=2&cursor=2&digest={first['preview_digest']}")
    assert stale.status_code == 409
    for bad in (
        {"sql": "1=1"},
        {"decisions": ["contact_now; DROP TABLE x"]},
        {"minimums": {"need_evidence": "unknown"}},
    ):
        response = new_campaign(client, operator, offer, rules=bad)
        assert response.status_code == 422, bad
    other = Org(app, "Other Org", "o")
    other_offer = publish_offer(app, other, code="other_campaign_offer")
    johar_other = client.post(
        "/api/v1/campaigns",
        json={"name": "Foreign offer", "offer_id": str(other_offer)},
        headers=mutation_headers(operator),
    )
    assert johar_other.status_code == 404


# --- CAMPAIGN-04 ------------------------------------------------------------------------------------------------


def test_campaign_04_stale_preview_between_read_and_selection_writes_nothing(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar, offer = ready(app, client, org, operator)
    campaign = new_campaign(client, operator, offer).json()
    row = item(preview(client, campaign["id"]), johar)
    from tests.integration.test_school_signals import _manual_fact  # noqa: PLC0415

    _manual_fact(app, org, johar, "school_levels", {"levels": ["primary", "secondary"]})  # evidence changed
    refused = approve(client, operator, campaign, row)
    assert refused.status_code == 409 and "stale" in refused.json()["error"]["message"]
    assert count(app, CampaignAccount) == 0 and count(app, CampaignDailyUsage) == 0
    assert "stale_assessment" in item(preview(client, campaign["id"]), johar)["reasons"]


# --- CAMPAIGN-05 ------------------------------------------------------------------------------------------------


def test_campaign_05_live_approval_blocked_without_quality_gate_fixture_mode_explicit(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar, offer = ready(app, client, org, operator)
    live = new_campaign(client, operator, offer, mode="live").json()
    assert "evidence_quality_gate_closed" in str(live["approval_blocked_reason"])
    row = item(preview(client, live["id"]), johar)
    assert "synthetic_account" in row["reasons"]
    blocked = approve(client, operator, live, row)
    assert blocked.status_code == 409 and "evidence_quality_gate_closed" in blocked.json()["error"]["message"]
    assert transition(client, operator, live["id"], "activate").status_code == 409
    fixture = new_campaign(client, operator, offer).json()
    approved = approve(client, operator, fixture, item(preview(client, fixture["id"]), johar))
    assert approved.status_code == 200 and approved.json()["stage"] == "approved_for_drafting"
    assert approved.json()["contact_authorized"] is False
    assert transition(client, operator, fixture["id"], "activate").status_code == 409  # fixture never active
    with db(app) as session, pytest.raises(Exception, match="(?i)production"):
        campaign_service.create(
            session,
            actor=org.actor,
            clock=app.state.clock,
            environment="production",
            name="Prod fixture",
            offer_id=offer,
            mode="fixture",
            district=None,
            target=campaign_rules.TargetRules(),
            budgets=campaign_rules.Budgets(),
        )


def test_campaign_05_live_approval_works_only_after_a_passed_real_evaluation(app: FastAPI, client: TestClient) -> None:
    team = Team(app, "lv")
    accounts = team.schools(30)
    csrf = logged_in(client, "operator@lv.example")
    run = create_eval(client, csrf, seed="gate").json()
    for row in eval_detail(client, run["id"])["item_list"]:
        judge(client, csrf, run["id"], row, "supported")
    assert finalize_eval(client, csrf, run["id"]).json()["state"] == "PASSED"
    offer = publish_offer(app, team)  # type: ignore[arg-type]
    assess(client, csrf, accounts[0], offer)
    live = new_campaign(client, csrf, offer, mode="live", rules={"decisions": ["investigate", "contact_now"]}).json()
    assert live["approval_blocked_reason"] is None
    row = item(preview(client, live["id"]), accounts[0])
    assert row["qualifies"] is True and row["provenance"] == "real"
    assert approve(client, csrf, live, row).json()["stage"] == "approved_for_drafting"
    assert transition(client, csrf, live["id"], "activate").json()["status"] == "active"


# --- CAMPAIGN-06 ------------------------------------------------------------------------------------------------


def test_campaign_06_parallel_approvals_replay_and_exclusion_converge(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar, offer = ready(app, client, org, operator)
    campaign = new_campaign(client, operator, offer).json()
    row = item(preview(client, campaign["id"]), johar)
    statuses: list[Any] = []
    barrier = threading.Barrier(2)

    def race() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        statuses.append(approve(local, token, campaign, row).json())

    threads = [threading.Thread(target=race) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(s["converged"] for s in statuses) == [False, True]
    assert count(app, CampaignAccount) == 1
    with db(app) as session:
        assert session.scalar(select(CampaignDailyUsage.used)) == 1  # quota consumed exactly once
    replay_key = key()
    first = approve(client, operator, campaign, row, replay_key).json()
    assert approve(client, operator, campaign, row, replay_key).json()["replayed"] is True and first["converged"]
    other = approve(client, operator, campaign | {"revision": 99}, row, replay_key)
    assert other.status_code == 409  # same key, different payload
    assert exclude(client, operator, campaign["id"], johar).json()["previous_stage"] == "approved_for_drafting"
    again = approve(client, operator, campaign, item(preview(client, campaign["id"]), johar))
    assert again.status_code == 409  # exclusion wins
    with db(app) as session:
        member = session.scalar(select(CampaignAccount))
        assert member is not None and member.stage == "excluded"


# --- CAMPAIGN-07 ------------------------------------------------------------------------------------------------


def test_campaign_07_local_day_budgets_are_exact(
    app: FastAPI, client: TestClient, org: Org, operator: str, clock: FixedClock
) -> None:
    _johar, offer = ready(app, client, org, operator)
    campaign_id = new_campaign(client, operator, offer, budgets={"approvals_per_day": 3}).json()["id"]
    with db(app) as session:
        campaign = session.get(Campaign, uuid.UUID(campaign_id))
        assert campaign is not None
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def take(at: datetime) -> None:
        barrier.wait(timeout=10)
        with db(app) as session:
            c = session.get(Campaign, uuid.UUID(campaign_id))
            assert c is not None
            results.append(campaign_service.consume_quota(session, c, "approval", 3, at))
            session.commit()

    late_evening = datetime(2026, 10, 23, 18, 59, tzinfo=UTC)  # 23:59 in Lahore
    threads = [threading.Thread(target=take, args=(late_evening,)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [False] * 5 + [True] * 3
    with db(app) as session:
        c = session.get(Campaign, uuid.UUID(campaign_id))
        assert c is not None
        after_midnight = datetime(2026, 10, 23, 19, 1, tzinfo=UTC)  # 00:01 the next Lahore day
        assert campaign_service.consume_quota(session, c, "approval", 3, after_midnight) is True
        assert campaign_service.consume_quota(session, c, "draft", 0, after_midnight) is False  # drafts budget 0
        session.commit()
        days = sorted((u.kind, u.day.isoformat(), u.used) for u in session.scalars(select(CampaignDailyUsage)))
    assert days == [("approval", "2026-10-23", 3), ("approval", "2026-10-24", 1), ("draft", "2026-10-24", 0)]


# --- CAMPAIGN-08 ------------------------------------------------------------------------------------------------


def test_campaign_08_pause_cancel_and_edits_preserve_blocks(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar, offer = ready(app, client, org, operator)
    campaign = new_campaign(client, operator, offer).json()
    assert approve(client, operator, campaign, item(preview(client, campaign["id"]), johar)).status_code == 200
    edited = client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        json={"expected_revision": 1, "rules": {"decisions": ["contact_now", "investigate"]}},
        headers=mutation_headers(operator),
    ).json()
    member = edited["members"][0]
    assert member["stale"] == ["rules_changed"] and member["drafting_blocked"] is True
    stale_edit = client.patch(
        f"/api/v1/campaigns/{campaign['id']}",
        json={"expected_revision": 1, "name": "Late"},
        headers=mutation_headers(operator),
    )
    assert stale_edit.status_code == 409
    paused = transition(client, operator, campaign["id"], "pause").json()
    assert paused["status"] == "paused"
    late = plain_account(app, org, "Paused Fixture School (Synthetic)")
    assert exclude(client, operator, campaign["id"], late).status_code == 200  # exclusion still wins while paused
    assert approve(client, operator, paused, item(preview(client, campaign["id"]), johar)).status_code == 409
    from app.offers import service as offer_service  # noqa: PLC0415
    from app.offers.models import Offer  # noqa: PLC0415

    with db(app) as session:
        current = session.get(Offer, offer)
        assert current is not None
        offer_service.archive(
            session, actor=org.actor, clock=app.state.clock, offer_id=offer, expected_version=current.version
        )
    view = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    assert view["offer_current"] is False and "offer_changed" in view["members"][0]["stale"]
    cancelled = transition(client, operator, campaign["id"], "cancel").json()
    assert cancelled["status"] == "cancelled"
    assert transition(client, operator, campaign["id"], "pause").status_code == 409
    with db(app) as session:
        stages = sorted(m.stage for m in session.scalars(select(CampaignAccount)))
    assert stages == ["approved_for_drafting", "excluded"]  # nothing progressed toward contact


# --- CAMPAIGN-09 ------------------------------------------------------------------------------------------------


def test_campaign_09_auth_scope_injection_and_zero_sends(app: FastAPI, client: TestClient, org: Org) -> None:
    offer = publish_offer(app, org)
    outbox = count(app, OutboxEvent)
    body = {"name": "<script>alert(1)</script> pilot", "offer_id": str(offer), "mode": "fixture"}
    assert client.post("/api/v1/campaigns", json=body).status_code == 401
    observer = logged_in(client, "observer@r.example")
    assert client.post("/api/v1/campaigns", json=body, headers=mutation_headers(observer)).status_code == 403
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert client.post("/api/v1/campaigns", json=body).status_code == 403  # missing CSRF
    assert (
        client.post("/api/v1/campaigns", json=body | {"send_now": True}, headers=mutation_headers(operator)).status_code
        == 422
    )
    created = client.post("/api/v1/campaigns", json=body, headers=mutation_headers(operator)).json()
    assert created["name"] == "<script>alert(1)</script> pilot"  # stored as text; the UI escapes it
    client.cookies.clear()
    observer = logged_in(client, "observer@r.example")
    assert client.get(f"/api/v1/campaigns/{created['id']}").status_code == 200
    assert transition(client, observer, created["id"], "pause").status_code == 403
    Org(app, "Other Org", "o")
    foreign = TestClient(app, raise_server_exceptions=False)
    token = logged_in(foreign, "operator@o.example")
    assert foreign.get(f"/api/v1/campaigns/{created['id']}").status_code == 404
    assert exclude(foreign, token, created["id"], uuid.uuid4()).status_code == 404
    assert foreign.get("/api/v1/campaigns").json()["items"] == []
    assert count(app, OutboxEvent) == outbox
    with db(app) as session:
        tables = set(session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))
    assert not {t for t in tables if any(w in t for w in ("message", "contact", "permission", "outreach"))}
