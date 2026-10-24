"""P2.4 acceptance RUN-01..RUN-09 (API + P1.5 worker + real Postgres; providers are offline or stubbed).

RUN-10 (browser journey) lives in apps/web/e2e/discovery.spec.ts.
"""

import random
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.accounts.models import Account, AccountAlias, AccountFact, ActionAudit
from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import FixedClock
from app.core.settings import Settings
from app.discovery import osm, runs
from app.discovery.models import DiscoveryCandidate, DiscoveryReviewDecision, DiscoveryRun, DiscoveryRunCandidate
from app.egress.https_client import UpstreamTransient
from app.jobs import registry as job_registry
from app.jobs import runner
from app.jobs.models import Job, OutboxEvent
from app.main import close_app, create_app
from app.resolution.models import CandidateAccountLink
from tests.integration.auth_helpers import add_organization, add_user, db, logged_in, mutation_headers
from tests.integration.test_discovery_live import BBOX, GOOD, FakeHttp, element, overpass, reviewed

FIXTURE = "fixture_lahore_schools"
REAL_BUILD_ADAPTER = runs.build_adapter
REASON = "Reviewed the listing and source link"


@pytest.fixture(autouse=True)
def worker_settings(monkeypatch: pytest.MonkeyPatch, app_settings: Settings) -> None:
    monkeypatch.setattr(runs, "SETTINGS", lambda: app_settings)


def worker(app: FastAPI, name: str = "worker-a") -> runner.JobRunner:
    clock: FixedClock = app.state.clock
    return runner.JobRunner(app.state.session_factory, worker_id=name, environment="test", sink=runner.NoSink(),
                            wake_client=None, heartbeat=lambda: None, now_fn=lambda _db: clock.now(),
                            rng=random.Random(7))  # fmt: skip


def org_with(app: FastAPI, name: str, roles: dict[str, Role]) -> uuid.UUID:
    org = add_organization(app, name)
    for email, role in roles.items():
        add_user(app, org, email, role=role)
    return org


def key() -> str:
    return f"run-{uuid.uuid4().hex[:16]}"


def start(client: TestClient, csrf: str, provider: str = FIXTURE, **budget: int) -> Any:
    body = {"provider": provider, "budget": {"max_candidates": 30, **budget}, "idempotency_key": key()}
    return client.post("/api/v1/discovery/runs", json=body, headers=mutation_headers(csrf))


def count(app: FastAPI, model: type[Any], **where: Any) -> int:
    with db(app) as session:
        query = select(func.count()).select_from(model)
        for name, value in where.items():
            query = query.where(getattr(model, name) == value)
        return int(session.scalar(query) or 0)


def decide(client: TestClient, csrf: str, run_id: str, item: dict[str, Any], action: str, **extra: Any) -> Any:
    body = {"action": action, "expected_version": item["version"], "idempotency_key": key(), "reason": REASON, **extra}
    return client.post(f"/api/v1/discovery/runs/{run_id}/candidates/{item['candidate_id']}/decision", json=body,
                       headers=mutation_headers(csrf))  # fmt: skip


@pytest.fixture
def operator(app: FastAPI, client: TestClient) -> Iterator[str]:
    org_with(app, "Runs Org", {"owner@runs.example": Role.OWNER, "operator@runs.example": Role.OPERATOR,
                               "observer@runs.example": Role.OBSERVER})  # fmt: skip
    yield logged_in(client, "operator@runs.example")


def completed_fixture_run(app: FastAPI, client: TestClient, csrf: str) -> tuple[str, list[dict[str, Any]]]:
    created = start(client, csrf)
    assert created.status_code == 202, created.text
    assert [o.status for o in worker(app).run_once()] == ["succeeded"]
    run_id = created.json()["id"]
    return run_id, client.get(f"/api/v1/discovery/runs/{run_id}/candidates").json()["items"]


# --- RUN-01 -----------------------------------------------------------------------------------------------


def test_run_01_operator_start_commits_run_job_and_outbox_atomically(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    sources = client.get("/api/v1/discovery/sources").json()
    assert [s["provider"] for s in sources["sources"]] == [FIXTURE]  # OSM is not offered while unreviewed
    assert sources["budget_ceilings"] == {"max_candidates": 30, "max_search_pages": 5, "max_fetches": 20,
                                          "max_seconds": 45}  # fmt: skip
    created = start(client, operator, max_candidates=10, max_seconds=30)
    assert created.status_code == 202, created.text
    run = created.json()
    assert (run["status"], run["provider"], run["synthetic"], run["exhaustive"]) == ("pending", FIXTURE, True, False)
    assert run["budget"] == {"max_candidates": 10, "max_search_pages": 5, "max_fetches": 20, "max_seconds": 30}
    with db(app) as session:
        job = session.scalar(select(Job))
        assert job is not None and (job.job_type, job.payload_json) == ("discovery.run", {"run_id": run["id"]})
        assert str(job.id) == run["job_id"] and job.status == "pending"
        event = session.scalar(select(OutboxEvent))
        assert event is not None and event.payload_json["job_id"] == run["job_id"]
        audit = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "discovery.run_requested"))
        assert audit is not None and audit.details_json["budget"]["max_candidates"] == 10


# --- RUN-02 -----------------------------------------------------------------------------------------------


def test_run_02_denials_happen_before_any_write(app: FastAPI, client: TestClient, operator: str) -> None:
    base = {"provider": FIXTURE, "budget": {"max_candidates": 5}, "idempotency_key": key()}
    assert client.post("/api/v1/discovery/runs", json=base).status_code == 403  # missing CSRF token
    for body, status in [
        ({**base, "provider": "osm_overpass_schools"}, 400),  # not reviewed: refused before enqueue
        ({**base, "provider": "google_places"}, 400),
        ({**base, "budget": {"max_candidates": 31}}, 422),
        ({**base, "budget": {"max_seconds": 600}}, 422),
        ({**base, "bbox": "30,73,32,75"}, 422),
        ({**base, "endpoint": "http://169.254.169.254/"}, 422),
        ({**base, "organization_id": str(uuid.uuid4())}, 422),
    ]:
        assert (
            client.post("/api/v1/discovery/runs", json=body, headers=mutation_headers(operator)).status_code == status
        )
    client.cookies.clear()
    csrf = logged_in(client, "observer@runs.example")
    assert client.get("/api/v1/discovery/runs").status_code == 200
    assert client.post("/api/v1/discovery/runs", json=base, headers=mutation_headers(csrf)).status_code == 403
    client.cookies.clear()
    assert client.post("/api/v1/discovery/runs", json=base).status_code == 401
    assert count(app, DiscoveryRun) == count(app, Job) == count(app, OutboxEvent) == 0

    csrf = logged_in(client, "operator@runs.example")
    run_id = start(client, csrf).json()["id"]
    org_with(app, "Other Org", {"owner@other.example": Role.OWNER})
    client.cookies.clear()
    other = logged_in(client, "owner@other.example")
    assert client.get(f"/api/v1/discovery/runs/{run_id}").status_code == 404
    assert client.get(f"/api/v1/discovery/runs/{run_id}/candidates").status_code == 404
    assert client.post(f"/api/v1/discovery/runs/{run_id}/cancel", headers=mutation_headers(other)).status_code == 404
    assert client.get("/api/v1/discovery/runs").json()["items"] == []


# --- RUN-03 -----------------------------------------------------------------------------------------------


def test_run_03_worker_progress_counts_and_evidence_survive_reload(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    created = start(client, operator)
    run_id = created.json()["id"]
    assert client.get(f"/api/v1/discovery/runs/{run_id}").json()["status"] == "pending"
    assert [o.status for o in worker(app).run_once()] == ["succeeded"]
    assert worker(app).run_once() == []
    run = client.get(f"/api/v1/discovery/runs/{run_id}").json()
    assert (run["status"], run["examined_count"], run["staged_count"], run["displayed_count"]) == ("completed", 9, 4, 4)
    assert run["rejected_count"] == 5 and run["truncated"] is False and run["job_status"] == "succeeded"
    assert run["usage"]["search_pages"] == 3 and run["review_counts"]["pending"] == 4 and run["exhaustive"] is False
    first = client.get(f"/api/v1/discovery/runs/{run_id}/candidates").json()
    again = client.get(f"/api/v1/discovery/runs/{run_id}/candidates").json()
    assert first == again and first["synthetic"] is True and len(first["items"]) == 4
    item = first["items"][0]
    assert item["verification"] == "unverified" and item["review_status"] == "pending"
    assert item["source_url"].startswith("https://school.fixture.example/")
    assert set(item["unknowns"]) >= {"ownership", "decision_authority", "software", "contactability", "need"}
    assert count(app, Account) == 0


# --- RUN-04 -----------------------------------------------------------------------------------------------


@pytest.fixture
def osm_app(
    app_settings: Settings, clock: FixedClock, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., FastAPI]]:
    """An app whose settings carry a complete owner review, with the Overpass transport stubbed."""
    live = reviewed(app_settings)
    monkeypatch.setattr(runs, "SETTINGS", lambda: live)
    made: list[FastAPI] = []

    def make(*responses: bytes | Exception) -> FastAPI:
        http = FakeHttp(*responses)
        monkeypatch.setattr(runs, "build_adapter", lambda provider, settings: osm.OsmOverpassAdapter(
            osm.descriptor_from_settings(settings), endpoint=settings.osm_endpoint, bbox=BBOX, http=http,
            now=clock.now))  # fmt: skip
        if not made:
            made.append(create_app(live, clock=clock))
        made[0].state.http = http
        return made[0]

    yield make
    for instance in made:
        close_app(instance)


def osm_run(osm_app: Callable[..., FastAPI], *responses: bytes | Exception) -> tuple[FastAPI, dict[str, Any]]:
    live = osm_app(*responses)
    client = TestClient(live, raise_server_exceptions=False)
    csrf = logged_in(client, "operator@runs.example")
    created = start(client, csrf, provider="osm_overpass_schools")
    assert created.status_code == 202, created.text
    worker(live).run_once()
    return live, client.get(f"/api/v1/discovery/runs/{created.json()['id']}").json()


def test_run_04_truncation_rate_limit_empty_and_stale_policy_are_truthful(
    app: FastAPI, operator: str, osm_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch,
    app_settings: Settings,
) -> None:  # fmt: skip
    many = [element("node", 7000 + i, f"Synthetic Bulk School {i:02d} (test)") for i in range(45)]
    live, run = osm_run(osm_app, overpass(many))
    assert (run["status"], run["truncated"], run["displayed_count"], run["stop_reason"]) == (
        "completed",
        True,
        30,
        "candidate_cap",
    )
    assert "OpenStreetMap contributors" in run["attribution"] and live.state.http.requests == 1

    _, limited = osm_run(osm_app, UpstreamTransient("rate_limited", 300.0))
    assert (limited["status"], limited["partial_reason"], limited["displayed_count"]) == ("partial", "rate_limited", 0)

    _, empty = osm_run(osm_app, overpass([]))
    assert (empty["status"], empty["displayed_count"], empty["truncated"]) == ("completed", 0, False)

    live = osm_app(overpass(GOOD))
    client = TestClient(live, raise_server_exceptions=False)
    csrf = logged_in(client, "operator@runs.example")
    run_id = start(client, csrf, provider="osm_overpass_schools").json()["id"]
    monkeypatch.setattr(runs, "SETTINGS", lambda: app_settings)  # owner withdrew the review before execution
    monkeypatch.setattr(runs, "build_adapter", REAL_BUILD_ADAPTER)
    worker(live).run_once()
    stale = client.get(f"/api/v1/discovery/runs/{run_id}").json()
    assert (stale["status"], stale["error_code"], stale["displayed_count"]) == ("failed", "provider_disabled", 0)
    assert live.state.http.requests == 0
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 30  # only the first run's


# --- RUN-05 -----------------------------------------------------------------------------------------------


def test_run_05_create_replay_conflict_and_duplicate_workers(app: FastAPI, client: TestClient, operator: str) -> None:
    body = {"provider": FIXTURE, "budget": {"max_candidates": 10}, "idempotency_key": "same-key-0001"}
    first = client.post("/api/v1/discovery/runs", json=body, headers=mutation_headers(operator))
    again = client.post("/api/v1/discovery/runs", json=body, headers=mutation_headers(operator))
    assert (first.status_code, again.status_code, again.json()["replayed"]) == (202, 202, True)
    assert first.json()["id"] == again.json()["id"]
    changed = {**body, "budget": {"max_candidates": 11}}
    assert client.post("/api/v1/discovery/runs", json=changed, headers=mutation_headers(operator)).status_code == 409
    assert count(app, DiscoveryRun) == count(app, Job) == 1

    clock: FixedClock = app.state.clock
    with db(app) as session:  # worker A claims, then stalls past its lease
        [stale] = runner.claim_due_jobs(session, worker_id="stalled", max_items=1, now=clock.now())
    clock.advance(timedelta(seconds=61))
    assert [o.status for o in worker(app, "rescuer").run_once()] == ["succeeded"]
    late = runner.execute(app.state.session_factory, stale, environment="test", now_fn=lambda _db: clock.now(),
                          rng=random.Random(1))  # fmt: skip
    assert late.status == "lease_lost"
    run = client.get(f"/api/v1/discovery/runs/{first.json()['id']}").json()
    assert (run["status"], run["displayed_count"]) == ("completed", 4)
    assert count(app, DiscoveryRunCandidate) == 4 and count(app, DiscoveryCandidate) == 4


def test_run_05_concurrent_identical_creates_make_one_run(app: FastAPI, operator: str) -> None:
    with db(app) as session:
        op = session.scalar(select(User).where(User.role == Role.OPERATOR))
        assert op is not None
        actor = Actor(user_id=op.id, organization_id=op.organization_id, role=Role.OPERATOR,
                      session_id=uuid.uuid4(), verifier="")  # fmt: skip
    results: list[Any] = []
    barrier = threading.Barrier(3)

    def create() -> None:
        barrier.wait(timeout=10)
        with db(app) as session:
            results.append(runs.create_run(session, actor=actor, clock=app.state.clock, settings=app.state.settings,
                                           provider=FIXTURE, budget=runs.RunBudget(max_candidates=5),
                                           idempotency_key="race-key-0001"))  # fmt: skip

    threads = [threading.Thread(target=create) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(created for _, created in results) == [False, False, True]
    assert len({run.id for run, _ in results}) == 1 and count(app, Job) == 1


# --- RUN-06 -----------------------------------------------------------------------------------------------


def test_run_06_accept_new_is_one_audited_account_with_source_proof(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    run_id, items = completed_fixture_run(app, client, operator)
    item = next(i for i in items if i["external_key"] == "gulberg-science")
    body = {"action": "accept_new", "expected_version": 1, "idempotency_key": "accept-key-001", "reason": REASON}
    url = f"/api/v1/discovery/runs/{run_id}/candidates/{item['candidate_id']}/decision"
    accepted = client.post(url, json=body, headers=mutation_headers(operator))
    assert accepted.status_code == 200, accepted.text
    account_id = accepted.json()["account_id"]
    replay = client.post(url, json=body, headers=mutation_headers(operator))
    assert replay.json() | {"replayed": False} == accepted.json() and replay.json()["replayed"] is True
    assert (
        client.post(url, json={**body, "reason": "Different reason"}, headers=mutation_headers(operator)).status_code
        == 409
    )
    assert count(app, Account) == 1 and count(app, DiscoveryReviewDecision) == 1
    detail = client.get(f"/api/v1/accounts/{account_id}").json()
    assert (detail["status"], detail["city"], detail["facts"]) == ("discovered", "Lahore", [])
    with db(app) as session:
        link = session.scalar(select(CandidateAccountLink))
        candidate = session.get(DiscoveryCandidate, uuid.UUID(item["candidate_id"]))
        audit = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "account.created"))
        assert link is not None and str(link.account_id) == account_id and candidate is not None
        assert candidate.status == "admitted" and audit is not None
        assert audit.details_json["origin"] == "discovery_review" and audit.details_json["source_record_id"]
    assert count(app, AccountFact) == 0  # nothing about needs, contacts or campuses is inferred


def test_run_06_concurrent_accepts_converge_on_one_account(app: FastAPI, client: TestClient, operator: str) -> None:
    run_id, items = completed_fixture_run(app, client, operator)
    item = items[0]
    add_user(app, _org(app), "operator2@runs.example", role=Role.OPERATOR)
    with db(app) as session:
        operators = list(session.scalars(select(User).where(User.role == Role.OPERATOR)))
    actors = [
        Actor(user_id=u.id, organization_id=u.organization_id, role=Role.OPERATOR, session_id=uuid.uuid4(), verifier="")
        for u in operators
    ]
    results: list[Any] = []
    barrier = threading.Barrier(2)

    def accept(actor: Any) -> None:
        barrier.wait(timeout=10)
        with db(app) as session:
            try:
                result = runs.review_candidate(
                    session, actor=actor, clock=app.state.clock, environment="test", run_id=uuid.UUID(run_id),
                    candidate_id=uuid.UUID(item["candidate_id"]), action="accept_new", expected_version=1,
                    idempotency_key=key(), reason=REASON,
                )  # fmt: skip
                results.append(result)
            except Exception as exc:  # noqa: BLE001  # asserted below
                results.append(exc)

    threads = [threading.Thread(target=accept, args=(a,)) for a in actors]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(isinstance(r, runs.ReviewResult) for r in results), results
    assert len({r.account_id for r in results}) == 1 and sorted(r.converged for r in results) == [False, True]
    assert count(app, Account) == 1 and count(app, CandidateAccountLink) == 1


def _org(app: FastAPI) -> uuid.UUID:
    with db(app) as session:
        run = session.scalar(select(DiscoveryRun))
        assert run is not None
        org: uuid.UUID = run.organization_id
        return org


# --- RUN-07 -----------------------------------------------------------------------------------------------


def test_run_07_attach_requires_reviewed_identity_and_reject_never_merges(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    run_id, items = completed_fixture_run(app, client, operator)
    target, other = items[0], items[1]
    body = {"canonical_name": "Unrelated Fixture Campus", "locality": "Gulberg"}
    existing = client.post("/api/v1/accounts", json=body, headers=mutation_headers(operator)).json()["id"]
    refused = decide(client, operator, run_id, target, "attach_existing", existing_account_id=existing)
    assert refused.status_code == 409 and "same campus" in refused.json()["error"]["message"]
    rejected = decide(client, operator, run_id, other, "reject")
    assert rejected.status_code == 200 and rejected.json()["review_status"] == "rejected"
    deferred = decide(client, operator, run_id, target, "defer")
    assert deferred.json()["review_status"] == "deferred"
    assert count(app, Account) == 1 and count(app, CandidateAccountLink) == 0  # only the manual account


def test_run_07_cancel_pending_and_running_never_resurrects_and_keeps_admissions(
    app: FastAPI, client: TestClient, operator: str, osm_app: Callable[..., FastAPI]
) -> None:
    run_id, items = completed_fixture_run(app, client, operator)
    admitted = decide(client, operator, run_id, items[0], "accept_new").json()["account_id"]

    pending = start(client, operator).json()["id"]
    cancelled = client.post(f"/api/v1/discovery/runs/{pending}/cancel", headers=mutation_headers(operator)).json()
    assert (cancelled["status"], cancelled["job_status"]) == ("cancelled", "cancelled")
    again = client.post(f"/api/v1/discovery/runs/{pending}/cancel", headers=mutation_headers(operator)).json()
    assert again["status"] == "cancelled" and again["version"] == cancelled["version"]
    assert worker(app).run_once() == []  # a cancelled job is never claimed

    live = osm_app(overpass(GOOD))
    live_client = TestClient(live, raise_server_exceptions=False)
    csrf = logged_in(live_client, "operator@runs.example")
    running = start(live_client, csrf, provider="osm_overpass_schools").json()["id"]
    live.state.http.on_call = lambda: live_client.post(f"/api/v1/discovery/runs/{running}/cancel",
                                                       headers=mutation_headers(csrf))  # fmt: skip
    worker(live).run_once()
    final = live_client.get(f"/api/v1/discovery/runs/{running}").json()
    assert (final["status"], final["stop_reason"], final["displayed_count"]) == ("cancelled", "cancelled", 0)
    with db(app) as session:  # a late duplicate delivery cannot resurrect it
        job = session.scalar(select(Job).where(Job.id == uuid.UUID(final["job_id"])))
        assert job is not None
        result = runs.handle_run_job(session, _ctx(job, app), job_registry.DiscoveryRunPayload(run_id=running))
        assert result["skipped"] is True
    assert live_client.get(f"/api/v1/discovery/runs/{running}").json()["status"] == "cancelled"
    assert client.get(f"/api/v1/accounts/{admitted}").status_code == 200  # admissions survive cancellations


def _ctx(job: Job, app: FastAPI) -> Any:
    return job_registry.JobContext(job.id, job.organization_id, 2, app.state.clock.now(), "test", 3)


# --- RUN-08 -----------------------------------------------------------------------------------------------


def test_run_08_expired_rights_stale_version_and_foreign_ids_are_refused(
    app: FastAPI, client: TestClient, operator: str, clock: FixedClock
) -> None:
    run_id, items = completed_fixture_run(app, client, operator)
    first, second = items[0], items[1]
    stale = {**second, "version": 7}
    assert decide(client, operator, run_id, stale, "defer").status_code == 409

    org_with(app, "Foreign Org", {"owner@foreign.example": Role.OWNER})
    foreign_client = TestClient(app, raise_server_exceptions=False)
    foreign = logged_in(foreign_client, "owner@foreign.example")
    foreign_account = foreign_client.post("/api/v1/accounts", json={"canonical_name": "Foreign Fixture School"},
                                          headers=mutation_headers(foreign)).json()["id"]  # fmt: skip
    assert (
        decide(client, operator, run_id, second, "attach_existing", existing_account_id=foreign_account).status_code
        == 404
    )
    assert decide(foreign_client, foreign, run_id, first, "accept_new").status_code == 404

    client.cookies.clear()
    observer = logged_in(client, "observer@runs.example")
    assert decide(client, observer, run_id, first, "accept_new").status_code == 403
    clock.advance(timedelta(days=400))  # past the 30-day provenance retention (sessions expire too)
    client.cookies.clear()
    csrf = logged_in(client, "operator@runs.example")
    expired = decide(client, csrf, run_id, first, "accept_new")
    assert expired.status_code == 409 and "rights_expired" in expired.json()["error"]["message"]
    assert count(app, Account, organization_id=_org(app)) == 0 and count(app, CandidateAccountLink) == 0


# --- RUN-09 -----------------------------------------------------------------------------------------------


def test_run_09_unicode_and_long_names_round_trip_and_survive_restart(
    app: FastAPI, operator: str, osm_app: Callable[..., FastAPI], app_settings: Settings, clock: FixedClock
) -> None:
    long_name = "Synthetic " + "Long Name School " * 14
    urdu = {"name:ur": "مصنوعی لاہور اسکول <b>ٹیسٹ</b>"}
    elements = [
        element("node", 9001, long_name.strip()[:250]),
        element("node", 9002, "Synthetic Urdu School", lat=31.45, lon=74.25, tags=urdu),
    ]
    live, run = osm_run(osm_app, overpass(elements))
    client = TestClient(live, raise_server_exceptions=False)
    csrf = logged_in(client, "operator@runs.example")
    items = client.get(f"/api/v1/discovery/runs/{run['id']}/candidates").json()["items"]
    by_key = {i["external_key"]: i for i in items}
    assert by_key["node/9002"]["name_local"] == "مصنوعی لاہور اسکول <b>ٹیسٹ</b>"  # raw text; the UI escapes it
    assert len(by_key["node/9001"]["display_name"]) == len(long_name.strip()[:250])
    accepted = decide(client, csrf, run["id"], by_key["node/9002"], "accept_new")
    assert accepted.status_code == 200, accepted.text
    account = accepted.json()["account_id"]
    with db(live) as session:
        aliases = list(session.scalars(select(AccountAlias.normalized_name)))
    assert any("مصنوعی" in a for a in aliases)  # the Urdu spelling is kept as an alias

    close_app(live)
    restarted = create_app(reviewed(app_settings), clock=clock)
    try:
        again = TestClient(restarted, raise_server_exceptions=False)
        logged_in(again, "operator@runs.example")
        reloaded = again.get(f"/api/v1/discovery/runs/{run['id']}").json()
        assert (reloaded["status"], reloaded["review_counts"]["accepted"]) == ("completed", 1)
        assert again.get(f"/api/v1/accounts/{account}").json()["canonical_name"] == "Synthetic Urdu School"
    finally:
        close_app(restarted)


def test_run_07_open_same_campus_match_blocks_new_account_until_decided(
    app: FastAPI, operator: str, osm_app: Callable[..., FastAPI]
) -> None:
    co_located = [element("node", 9101, "Synthetic Roots School"), element("node", 9102, "Synthetic Maarif School")]
    live, run = osm_run(osm_app, overpass(co_located))
    client = TestClient(live, raise_server_exceptions=False)
    csrf = logged_in(client, "operator@runs.example")
    items = client.get(f"/api/v1/discovery/runs/{run['id']}/candidates").json()["items"]
    (match,) = items[0]["matches"]
    assert (match["resolution"], match["reason_codes"]) == ("suggest_review", ["co_located_different_names"])
    blocked = decide(client, csrf, run["id"], items[0], "accept_new")
    assert blocked.status_code == 409 and "same-campus" in blocked.json()["error"]["message"]
    assert count(app, Account) == 0
    distinct = client.post(
        f"/api/v1/identity/suggestions/{match['suggestion_id']}/decisions",
        json={"command_id": str(uuid.uuid4()), "action": "mark_distinct", "expected_version": match["version"],
              "reason": "Two schools share one compound"},
        headers=mutation_headers(csrf),
    )  # fmt: skip
    assert distinct.status_code == 200
    accepted = decide(client, csrf, run["id"], items[0], "accept_new")
    assert accepted.status_code == 200 and count(app, Account) == 1


def test_run_04_worker_enforces_the_snapshotted_operator_budget(
    app: FastAPI, client: TestClient, operator: str
) -> None:
    created = start(client, operator, max_candidates=2, max_search_pages=1)
    assert created.status_code == 202
    worker(app).run_once()
    run = client.get(f"/api/v1/discovery/runs/{created.json()['id']}").json()
    assert (run["displayed_count"], run["usage"]["search_pages"]) == (2, 1)
    assert run["truncated"] is True and run["status"] == "completed" and run["stop_reason"] == "candidate_cap"
    assert count(app, DiscoveryRunCandidate) == 2
