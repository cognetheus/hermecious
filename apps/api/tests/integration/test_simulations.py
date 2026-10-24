"""P4.5 acceptance SIM-01..09 (API + Postgres + the P1.5 runner, fixture mode). SIM-10 is e2e + auth here.

Synthetic accounts and zero-filled numbers only. The simulator's only transport is the in-process fake.
"""

import csv
import io
import socket
import threading
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.clock import FixedClock
from app.jobs import registry
from app.jobs.models import Job, OutboxEvent
from app.simulations import service as sim_service
from app.simulations import transport
from app.simulations.models import SimulationItem
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_approvals import Setup, approve
from tests.integration.test_campaigns import approve as approve_member
from tests.integration.test_campaigns import exclude, item, new_campaign, plain_account, preview, transition
from tests.integration.test_drafts import draft
from tests.integration.test_eligibility import add_contact, record, review, revoke
from tests.integration.test_qualification import assess
from tests.integration.test_research import JOHAR, Org, worker
from tests.integration.test_school_signals import accept, researched

pytestmark = pytest.mark.usefixtures("app")
LABEL = "SIMULATION ONLY — 0 real messages sent"


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


@pytest.fixture
def world(app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]) -> "World":
    return World(app, client, org, operator, owner)


def key() -> str:
    return f"sim-test-{uuid.uuid4().hex[:12]}"


class World:
    """A fixture campaign whose first account has approved, simulation-eligible content."""

    def __init__(
        self, app: FastAPI, client: TestClient, org: Org, operator: str, owner: tuple[TestClient, str]
    ) -> None:
        self.app, self.client, self.org, self.operator, self.owner = app, client, org, operator, owner
        setup = Setup(app, client, org, operator, owner)
        self.campaign, self.offer = setup.campaign, setup.offer
        self.first = (setup.account, setup.contact, setup.permission)
        assert approve(client, operator, setup.draft, setup.contact).status_code == 201

    def second(self, number: str = "+92 000 0000111", approve_content: bool = True) -> tuple[uuid.UUID, str, str]:
        """A second qualifying synthetic account (same fixture document), approved into the same campaign."""
        client, csrf = self.client, self.operator
        account = self.org.account("Crescent Valley Grammar Annex (Synthetic)", "Johar Town", JOHAR)
        claims = researched(self.app, client, csrf, account, self.org.source(JOHAR))
        accept(client, csrf, claims, count=2)
        accept(client, csrf, claims, signal="admissions process announced")
        accept(client, csrf, claims, area="fees")
        accept(client, csrf, claims, channel="website_form")
        assert assess(client, csrf, account, self.offer).json()["decision"] == "contact_now"
        campaign = client.get(f"/api/v1/campaigns/{self.campaign['id']}").json()
        assert approve_member(client, csrf, campaign, item(preview(client, campaign["id"]), account)).status_code == 200
        created = draft(client, csrf, self.campaign["id"], account).json()
        contact = add_contact(client, csrf, account, number).json()["id"]
        permission = record(client, csrf, contact).json()["permission_id"]
        assert review(self.owner[0], self.owner[1], contact, permission).status_code == 201
        if approve_content:
            assert approve(client, csrf, created, contact).status_code == 201
        return account, contact, permission

    def run(self, scenario: str = "all_allow", max_items: int = 30, idem: str | None = None) -> Any:
        return self.client.post(
            f"/api/v1/campaigns/{self.campaign['id']}/simulations",
            json={"scenario": scenario, "max_items": max_items, "idempotency_key": idem or key()},
            headers=mutation_headers(self.operator),
        )

    def execute(self, scenario: str = "all_allow", **kw: Any) -> dict[str, Any]:
        started = self.run(scenario, **kw)
        assert started.status_code == 201, started.text
        outcomes = worker(self.app).run_once()
        assert [o.status for o in outcomes] == ["succeeded"], outcomes
        return self.detail(started.json()["id"])

    def detail(self, run_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self.client.get(f"/api/v1/campaigns/{self.campaign['id']}/simulations/{run_id}").json()
        return result

    def relogin(self) -> None:
        self.client.cookies.clear()
        self.operator = logged_in(self.client, "operator@r.example")


def of(run: dict[str, Any], account: uuid.UUID) -> dict[str, Any]:
    found: dict[str, Any] = next(i for i in run["items"] if i["account_id"] == str(account))
    return found


def jobs_and_events(app: FastAPI) -> tuple[list[str], list[str]]:
    with db(app) as session:
        return (
            list(session.scalars(select(Job.job_type))),
            list(session.scalars(select(OutboxEvent.event_type))),
        )


# --- SIM-01 ------------------------------------------------------------------------------------------------------


def test_sim_01_deterministic_eligible_run_fake_delivery_only(app: FastAPI, world: World) -> None:
    run = world.execute()
    assert (run["status"], run["label"], run["real_messages_sent"], run["mode"]) == ("completed", LABEL, 0, "fixture")
    first = of(run, world.first[0])
    assert (first["bucket"], first["lifecycle"], first["attempts"]) == ("accepted", "sim_delivered", 1)
    assert first["sim_receipt_id"].startswith("sim-") and len(first["sim_receipt_id"]) == 28
    report = run["report"]
    assert report["label"] == LABEL and report["reconciled"] is True and report["considered"] == run["considered"]
    assert report["buckets"]["accepted"] == {"count": 1, "denominator": run["considered"], "percent": round(
        100 / run["considered"], 1), "kind": "simulated"}  # fmt: skip
    assert report["lifecycle"]["sim_delivered"]["denominator"] == 1
    again = world.execute()
    assert again["report_digest"] == run["report_digest"]  # same state -> same report
    job_types, events = jobs_and_events(app)
    assert {t for t in job_types if t.startswith("simulation")} == {"simulation.run"}
    assert not [e for e in events if any(w in e for w in ("send", "message", "deliver", "whatsapp"))]


# --- SIM-02 ------------------------------------------------------------------------------------------------------


def test_sim_02_no_consent_and_revocation_are_denied(app: FastAPI, client: TestClient, world: World) -> None:
    unconsented = plain_account(app, world.org, "Shadman Model School (Synthetic)")
    add_contact(client, world.operator, unconsented, "+92 000 0000120")
    no_contact = plain_account(app, world.org, "Ravi Road School (Synthetic)")
    account, contact, permission = world.first
    assert revoke(client, world.operator, contact, permission, 2).status_code == 201
    run = world.execute()
    first = of(run, account)
    assert first["bucket"] == "denied" and first["lifecycle"] == "not_attempted" and first["sim_receipt_id"] is None
    assert {"approval_approval_stale", "eligibility_permission_revoked", "permission_changed"} <= set(first["reasons"])
    assert of(run, unconsented)["reasons"] == ["not_approved_for_drafting"]
    assert (of(run, no_contact)["bucket"], of(run, no_contact)["reasons"]) == ("invalid", ["no_contact"])
    assert run["report"]["buckets"]["accepted"]["count"] == 0
    assert "real opt-in" in run["report"]["missing_prerequisites"]


# --- SIM-03 ------------------------------------------------------------------------------------------------------


def test_sim_03_opt_out_mid_run_blocks_remaining_recipients_and_other_campaigns(
    app: FastAPI, client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, second_contact, _ = world.second()
    simulated = world.execute("opt_out_mid_run")
    buckets = sorted(of(simulated, a)["bucket"] for a in (world.first[0], second))
    assert buckets == ["accepted", "denied"]
    denied = next(of(simulated, a) for a in (world.first[0], second) if of(simulated, a)["bucket"] == "denied")
    assert denied["reasons"] == ["suppressed", "simulated_opt_out"] and denied["sim_receipt_id"] is None
    assert simulated["report"]["lifecycle"]["sim_delivered"]["count"] == 1  # an opt-out is never a delivery
    # A real opt-out recorded while a run is in progress denies every remaining recipient with that number.
    real_item = sim_service._item
    order: list[uuid.UUID] = []

    def item_then_opt_out(db_: Any, run: Any, campaign: Any, account: Any, *rest: Any) -> Any:
        result = real_item(db_, run, campaign, account, *rest)
        order.append(account.id)
        if len(order) == 1:  # after the first recipient, both numbers opt out
            for contact in (world.first[1], second_contact):
                assert sim_service_suppress(app, world.org, contact)
        return result

    monkeypatch.setattr(sim_service, "_item", item_then_opt_out)
    live = world.execute()
    later = of(live, order[1])  # the recipient evaluated after the opt-out
    assert later["bucket"] == "denied"
    assert "eligibility_suppressed" in later["reasons"]
    # ...and in any other campaign.
    other = new_campaign(client, world.operator, world.offer, name="Second pilot").json()
    checked = client.post(
        "/api/v1/channel-eligibility/evaluate",
        json={"contact_id": second_contact, "purpose": "marketing", "campaign_id": other["id"]},
        headers=mutation_headers(world.operator),
    ).json()
    assert checked["decision"] == "deny" and "suppressed" in [r["code"] for r in checked["reasons"]]


def sim_service_suppress(app: FastAPI, org: Org, contact: str) -> bool:
    from app.contacts import service as contacts  # noqa: PLC0415

    with db(app) as session:
        outcome, _ = contacts.suppress(
            session, actor=org.actor, clock=app.state.clock, contact_id=uuid.UUID(contact), reason="opt_out",
            idempotency_key=key(),
        )  # fmt: skip
    return bool(outcome["suppressed"])


# --- SIM-04 ------------------------------------------------------------------------------------------------------


def test_sim_04_unapproved_stale_content_paused_campaign_and_changed_offer_block(
    app: FastAPI, client: TestClient, world: World
) -> None:
    second, _contact, _ = world.second(approve_content=False)
    run = world.execute("stale_approval")
    stale = of(run, world.first[0])
    assert stale["bucket"] == "denied" and "approval_expired" in stale["reasons"]
    assert of(run, second)["reasons"] == ["approval_not_reviewed"]
    assert transition(client, world.operator, world.campaign["id"], "pause").status_code == 200
    paused = of(world.execute(), world.first[0])
    assert paused["bucket"] == "denied" and "campaign_paused" in paused["reasons"]
    from app.offers import service as offer_service  # noqa: PLC0415
    from app.offers.models import Offer  # noqa: PLC0415

    with db(app) as session:
        current = session.get(Offer, world.offer)
        assert current is not None
        offer_service.archive(
            session, actor=world.org.actor, clock=app.state.clock, offer_id=world.offer,
            expected_version=current.version,
        )  # fmt: skip
    changed = of(world.execute(), world.first[0])
    assert "offer_not_published" in changed["reasons"]
    assert "fresh evidence" in world.execute()["report"]["missing_prerequisites"]


# --- SIM-05 ------------------------------------------------------------------------------------------------------


def test_sim_05_quiet_hours_weekend_and_local_day_caps(world: World, clock: FixedClock) -> None:
    second, _contact, _ = world.second()
    quiet = of(world.execute("quiet_hours"), world.first[0])  # 19:00 Friday Asia/Karachi
    assert (quiet["bucket"], quiet["reasons"]) == ("deferred", ["outside_business_hours"])
    assert quiet["next_window_at"] == "2026-10-24T04:00:00+00:00"  # Saturday 09:00 Asia/Karachi
    capped = world.execute("quota")
    buckets = {of(capped, a)["bucket"] for a in (world.first[0], second)}
    assert buckets == {"accepted", "deferred"}
    deferred = next(of(capped, a) for a in (world.first[0], second) if of(capped, a)["bucket"] == "deferred")
    assert deferred["reasons"] == ["daily_cap_reached"]
    assert deferred["next_window_at"] == "2026-10-24T04:00:00+00:00"  # the next Asia/Karachi day, at opening
    clock.advance(timedelta(hours=30))  # Saturday 18:00 Asia/Karachi (13:00 UTC): closing time
    world.relogin()
    weekend = of(world.execute(), world.first[0])
    assert (weekend["bucket"], weekend["next_window_at"]) == ("deferred", "2026-10-26T04:00:00+00:00")  # Monday
    # Simulated deliveries are per run: they never count toward real caps or later runs.
    clock.advance(timedelta(hours=-30))
    world.relogin()
    assert of(world.execute(), world.first[0])["bucket"] == "accepted"


# --- SIM-06 ------------------------------------------------------------------------------------------------------


def test_sim_06_mock_429_timeout_and_worker_restart_are_bounded_and_converge(
    app: FastAPI, world: World, clock: FixedClock
) -> None:
    second, _contact, _ = world.second()
    limited = of(world.execute("provider_429_mock"), world.first[0])
    assert (limited["lifecycle"], limited["attempts"]) == ("sim_delivered", 2)
    assert limited["reasons"] == ["sim_rate_limited_attempt_1"]
    timeout_run = world.execute("transport_timeout_mock")
    timed_out = of(timeout_run, world.first[0])
    assert (timed_out["lifecycle"], timed_out["attempts"], timed_out["sim_receipt_id"]) == ("sim_failed", 3, None)
    assert timeout_run["report"]["lifecycle"]["sim_failed"]["count"] == 2
    started = world.run("worker_restart_mock").json()
    assert [o.status for o in worker(app).run_once()] == ["retry_wait"]  # the worker "dies" part-way
    partial = world.detail(started["id"])
    assert partial["status"] == "running" and len(partial["items"]) == 1  # the first half was durable
    clock.advance(timedelta(minutes=5))
    assert [o.status for o in worker(app).run_once()] == ["succeeded"]
    finished = world.detail(started["id"])
    assert finished["status"] == "completed" and finished["considered"] == len(finished["items"])
    assert len({i["account_id"] for i in finished["items"]}) == len(finished["items"])  # one result per account
    receipts = [i["sim_receipt_id"] for i in finished["items"] if i["sim_receipt_id"]]
    assert len(receipts) == len(set(receipts)) == 2
    with db(app) as session:
        rows = session.scalar(
            select(func.count()).select_from(SimulationItem).where(SimulationItem.run_id == uuid.UUID(started["id"]))
        )
    assert rows == finished["considered"] == 2 and of(finished, second)["sim_receipt_id"]


# --- SIM-07 ------------------------------------------------------------------------------------------------------


def test_sim_07_concurrent_runs_idempotency_and_cancel(app: FastAPI, client: TestClient, world: World) -> None:
    def race(make: Any) -> list[int]:
        statuses: list[int] = []
        barrier = threading.Barrier(2)

        def one() -> None:
            local = TestClient(app, raise_server_exceptions=False)
            token = logged_in(local, "operator@r.example")
            barrier.wait(timeout=10)
            statuses.append(make(local, token).status_code)

        threads = [threading.Thread(target=one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return sorted(statuses)

    url = f"/api/v1/campaigns/{world.campaign['id']}/simulations"
    shared = key()
    same = race(lambda c, t: c.post(url, json={"idempotency_key": shared}, headers=mutation_headers(t)))
    assert same == [200, 201]
    conflict = client.post(
        url, json={"idempotency_key": shared, "scenario": "quota"}, headers=mutation_headers(world.operator)
    )
    assert conflict.status_code == 409
    busy = world.run()
    assert busy.status_code == 409 and "already active" in busy.json()["error"]["message"]
    runs = client.get(url).json()["items"]
    assert len(runs) == 1 and runs[0]["status"] == "pending"
    cancelled = client.post(f"{url}/{runs[0]['id']}/cancel", headers=mutation_headers(world.operator)).json()
    assert cancelled["status"] == "cancelled" and cancelled["items"] == []
    assert worker(app).run_once() == []  # the cancelled job never runs
    distinct = race(lambda c, t: c.post(url, json={"idempotency_key": key()}, headers=mutation_headers(t)))
    assert distinct == [201, 409]  # one active run per campaign


# --- SIM-08 ------------------------------------------------------------------------------------------------------


def test_sim_08_thirty_item_mixed_report_reconciles_with_redacted_export(
    app: FastAPI, client: TestClient, world: World
) -> None:
    world.second()
    for n in range(30):
        name = (
            f'=HYPERLINK("http://evil") School {n:02d} (Synthetic)' if n == 0 else f"Lahore School {n:02d} (Synthetic)"
        )
        account = plain_account(app, world.org, name)
        if n % 3 == 0:
            add_contact(client, world.operator, account, f"+92 000 00{n + 300:05d}")
        if n % 5 == 0:
            exclude(client, world.operator, world.campaign["id"], account)
    run = world.execute("quota", max_items=30)
    report = run["report"]
    assert run["considered"] == 30 == report["considered"] == len(run["items"])  # bounded at 30
    counts = {b: report["buckets"][b]["count"] for b in ("accepted", "denied", "deferred", "invalid")}
    assert sum(counts.values()) == 30 and counts["accepted"] == 1 and counts["deferred"] == 1
    assert counts["denied"] >= 1 and counts["invalid"] >= 1 and report["reconciled"] is True
    assert all(report["buckets"][b]["denominator"] == 30 for b in counts)
    assert report["lifecycle"]["sim_delivered"] == {"count": 1, "denominator": 1, "percent": 100.0, "kind": "simulated"}
    assert set(report["missing_prerequisites"]) >= {"contact on record", "campaign membership"}
    exported = client.get(f"/api/v1/campaigns/{world.campaign['id']}/simulations/{run['id']}/export.csv")
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    body = exported.text
    assert body.splitlines()[0] == f"# {LABEL}"
    rows = list(csv.reader(io.StringIO(body)))[3:]
    assert len(rows) == 30
    assert all(not r[1].startswith(("=", "+", "-", "@")) for r in rows)
    assert any(r[1].startswith("'=HYPERLINK") for r in rows)
    assert "+92" not in body and "Assalam" not in body  # no numbers, no message bodies


# --- SIM-09 ------------------------------------------------------------------------------------------------------


def test_sim_09_network_spy_registry_and_kill_switch_prove_zero_real_sends(
    app: FastAPI, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    connects: list[Any] = []
    real_connect = socket.socket.connect

    def spy(self: socket.socket, address: Any) -> Any:
        connects.append(address)
        return real_connect(self, address)

    def no_egress(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the simulator must never build an egress client")

    from app.egress import https_client  # noqa: PLC0415

    monkeypatch.setattr(socket.socket, "connect", spy)
    monkeypatch.setattr(https_client.PinnedHttpsClient, "__init__", no_egress)
    monkeypatch.setenv("HERMECIOUS_LIVE_OUTBOUND_ENABLED", "true")  # cannot enable anything in P4.x
    run = world.execute()
    assert of(run, world.first[0])["lifecycle"] == "sim_delivered"
    assert connects == []  # no socket was opened while the run executed (Postgres uses libpq, not Python sockets)
    with pytest.raises(transport.LiveTransportForbidden):
        transport.live_transport()
    source = "\n".join(p.read_text() for p in Path(sim_service.__file__).parent.glob("*.py"))
    for forbidden in ("httpx", "requests", "urllib", "import socket", "app.egress", "aiohttp", "twilio", "whatsapp_"):
        assert forbidden not in source, forbidden
    import sys  # noqa: PLC0415

    assert not [m for m in sys.modules if any(w in m.lower() for w in ("twilio", "pywa", "heyoo", "whatsapp"))]
    assert not [t for t, _v in registry.REGISTRY if any(w in t for w in ("send", "message", "dispatch", "deliver"))]
    with db(app) as session:
        tables = set(session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))
        assert not {t for t in tables if any(w in t for w in ("message", "outbound", "delivery", "send"))}
        with pytest.raises(DBAPIError, match="zero_real_messages"):
            session.execute(text("UPDATE simulation_runs SET real_messages_sent = 1"))
    monkeypatch.setenv("HERMECIOUS_OUTREACH_KILL_SWITCH", "true")
    stopped = of(world.execute(), world.first[0])
    assert stopped["bucket"] == "denied" and "eligibility_kill_switch_engaged" in stopped["reasons"]


# --- SIM-10 (API part; the UI journey is e2e) --------------------------------------------------------------------


def test_sim_10_auth_csrf_cross_org_and_bounds(app: FastAPI, client: TestClient, world: World) -> None:
    url = f"/api/v1/campaigns/{world.campaign['id']}/simulations"
    assert client.post(url, json={"idempotency_key": key()}).status_code == 403  # no CSRF
    headers = mutation_headers(world.operator)
    assert client.post(url, json={"idempotency_key": key(), "max_items": 31}, headers=headers).status_code == 422
    assert client.post(url, json={"idempotency_key": key(), "send": True}, headers=headers).status_code == 422
    assert client.post(url, json={"idempotency_key": key(), "scenario": "live"}, headers=headers).status_code == 422
    run = world.execute()
    observer = TestClient(app, raise_server_exceptions=False)
    token = logged_in(observer, "observer@r.example")
    assert observer.get(f"{url}/{run['id']}").status_code == 200
    assert observer.post(url, json={"idempotency_key": key()}, headers=mutation_headers(token)).status_code == 403
    assert observer.post(f"{url}/{run['id']}/cancel", headers=mutation_headers(token)).status_code == 403
    Org(app, "Other Org", "o")
    foreign = TestClient(app, raise_server_exceptions=False)
    other = logged_in(foreign, "operator@o.example")
    assert foreign.get(f"{url}/{run['id']}").status_code == 404
    assert foreign.get(f"{url}/{run['id']}/export.csv").status_code == 404
    assert foreign.post(url, json={"idempotency_key": key()}, headers=mutation_headers(other)).status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401


# --- Guards that only race or misconfiguration can reach (mutation follow-up) ------------------------------------


def test_sim_03_suppression_between_approval_and_eligibility_reads_still_denies(
    app: FastAPI, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An opt-out that commits after the approval check but before the policy check must still win."""
    from app.approvals import service as approvals  # noqa: PLC0415

    real_status = approvals.status

    def status_then_opt_out(*args: Any, **kwargs: Any) -> Any:
        result = real_status(*args, **kwargs)
        sim_service_suppress(app, world.org, world.first[1])
        return result

    monkeypatch.setattr(approvals, "status", status_then_opt_out)
    raced = of(world.execute(), world.first[0])
    assert (raced["bucket"], raced["lifecycle"], raced["sim_receipt_id"]) == ("denied", "not_attempted", None)
    assert "suppressed" in raced["reasons"]


def test_sim_readiness_mode_never_simulates_delivery(app: FastAPI, world: World) -> None:
    """Readiness runs (live campaigns, production) report gaps but never reach the transport."""
    started = world.run().json()
    with db(app) as session:
        session.execute(text("UPDATE simulation_runs SET mode = 'readiness' WHERE id = :i"), {"i": started["id"]})
        session.commit()
    assert [o.status for o in worker(app).run_once()] == ["succeeded"]
    first = of(world.detail(started["id"]), world.first[0])
    assert first["bucket"] == "denied" and first["reasons"] == ["readiness_only_no_simulated_delivery"]
    assert first["lifecycle"] == "not_attempted" and first["sim_receipt_id"] is None


def test_sim_07_cancel_requested_mid_run_stops_remaining_items(
    app: FastAPI, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.second()
    real_item = sim_service._item
    calls: list[int] = []

    def item_then_cancel(db_: Any, run: Any, *rest: Any) -> Any:
        result = real_item(db_, run, *rest)
        calls.append(1)
        if len(calls) == 1:
            with db(app) as session:
                sim_service.cancel_run(
                    session, actor=world.org.actor, clock=app.state.clock, campaign_id=run.campaign_id, run_id=run.id
                )
        return result

    monkeypatch.setattr(sim_service, "_item", item_then_cancel)
    run = world.execute()
    assert run["status"] == "cancelled" and run["considered"] == len(run["items"]) == 1
    assert run["report"]["considered"] == 1 and run["report"]["reconciled"] is True
