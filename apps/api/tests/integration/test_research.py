"""P3.1 acceptance RESEARCH-01..RESEARCH-09 (fixture documents; real Postgres and P1.5 worker). RESEARCH-10 is e2e."""

import random
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.accounts import service as account_service
from app.accounts.models import AccountFact, ActionAudit, SourceRecord
from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import FixedClock
from app.discovery.contracts import SourceQuery
from app.discovery.fixture import FixtureLahoreSchoolsAdapter
from app.discovery.runner import run_discovery
from app.jobs import runner
from app.jobs.models import Job, OutboxEvent
from app.research import documents, service
from app.research.models import ResearchClaim, ResearchObservation, ResearchRun
from tests.integration.auth_helpers import add_organization, add_user, db, logged_in, mutation_headers

JOHAR, RAVI, DHA = "cvg-johar-town", "ravi-bank-shahdara", "cvg-dha-phase-5"
REASON = "Checked the cited sentence on the source page"


def worker(app: FastAPI, name: str = "worker-a") -> runner.JobRunner:
    clock: FixedClock = app.state.clock
    return runner.JobRunner(app.state.session_factory, worker_id=name, environment="test", sink=runner.NoSink(),
                            wake_client=None, heartbeat=lambda: None, now_fn=lambda _db: clock.now(),
                            rng=random.Random(3))  # fmt: skip


def key() -> str:
    return f"res-{uuid.uuid4().hex[:16]}"


def count(app: FastAPI, model: type[Any], **where: Any) -> int:
    with db(app) as session:
        query = select(func.count()).select_from(model)
        for name, value in where.items():
            query = query.where(getattr(model, name) == value)
        return int(session.scalar(query) or 0)


class Org:
    def __init__(self, app: FastAPI, name: str = "Research Org", prefix: str = "r") -> None:
        self.id = add_organization(app, name)
        self.owner = add_user(app, self.id, f"owner@{prefix}.example", role=Role.OWNER)
        add_user(app, self.id, f"operator@{prefix}.example", role=Role.OPERATOR)
        add_user(app, self.id, f"observer@{prefix}.example", role=Role.OBSERVER)
        self.prefix = prefix
        self.actor = Actor(user_id=self.owner, organization_id=self.id, role=Role.OWNER, session_id=uuid.uuid4(),
                           verifier="")  # fmt: skip
        with db(app) as session:  # fixture provenance rows (fictional schools), via the P2.1 runner
            run_discovery(
                session, actor=self.actor, clock=app.state.clock, environment="test",
                adapter=FixtureLahoreSchoolsAdapter(), query=SourceQuery(city="Lahore", vertical_slug="schools"),
            )  # fmt: skip
        self.app = app

    def source(self, fixture_key: str) -> uuid.UUID:
        with db(self.app) as session:
            found = session.scalar(select(SourceRecord.id).where(
                SourceRecord.organization_id == self.id,
                SourceRecord.external_key == f"fixture_lahore_schools:{fixture_key}"))  # fmt: skip
        assert found is not None
        return found

    def account(self, name: str, locality: str, *sources: str) -> uuid.UUID:
        """An account tied to fixture sources through alias provenance (an explicit association)."""
        with db(self.app) as session:
            from app.accounts import management  # noqa: PLC0415
            from app.accounts.models import Vertical  # noqa: PLC0415

            vertical = session.scalar(select(Vertical.id).where(Vertical.slug == "schools"))
            assert vertical is not None
            account_id = management.create(session, actor=self.actor, clock=self.app.state.clock, vertical_id=vertical,
                                           name=name, city="Lahore", locality=locality).id  # fmt: skip
        for i, fixture_key in enumerate(sources):
            with db(self.app) as session:
                account_service.add_alias(
                    session, actor=self.actor, clock=self.app.state.clock, account_id=account_id,
                    name=f"{name} source {i}", source_record_id=self.source(fixture_key),
                )  # fmt: skip
        return account_id


@pytest.fixture
def org(app: FastAPI) -> Org:
    return Org(app)


@pytest.fixture
def operator(app: FastAPI, client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


def start(client: TestClient, csrf: str, account_id: uuid.UUID, *sources: uuid.UUID, idem: str | None = None) -> Any:
    body = {"source_record_ids": [str(s) for s in sources], "idempotency_key": idem or key()}
    return client.post(f"/api/v1/accounts/{account_id}/research-runs", json=body, headers=mutation_headers(csrf))


def finished(app: FastAPI, client: TestClient, run_id: str) -> dict[str, Any]:
    worker(app).run_once()
    detail: dict[str, Any] = client.get(f"/api/v1/research-runs/{run_id}").json()
    return detail


def review(client: TestClient, csrf: str, claim: dict[str, Any], action: str = "accept", **extra: Any) -> Any:
    body = {"action": action, "expected_version": claim["version"], "reason": REASON, "idempotency_key": key(), **extra}
    return client.post(f"/api/v1/research-claims/{claim['id']}/review", json=body, headers=mutation_headers(csrf))


class ScriptedFetcher:
    """Replaces the fixture fetcher: per-key responses or errors, optional side effects, fetch log."""

    def __init__(self, responses: dict[str, Any], on_fetch: Any = None) -> None:
        self.responses, self.on_fetch, self.calls = responses, on_fetch, []  # type: ignore[var-annotated]

    def fetch(self, *, provider: str, source_key: str, now: datetime) -> documents.RawDocument:
        self.calls.append(source_key)
        if self.on_fetch:
            self.on_fetch(source_key)
        response = self.responses.get(source_key)
        if response is None:
            return documents.FixtureDocumentFetcher().fetch(provider=provider, source_key=source_key, now=now)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[no-any-return]


@pytest.fixture
def fetcher(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def install(responses: dict[str, Any], on_fetch: Any = None) -> ScriptedFetcher:
        scripted = ScriptedFetcher(responses, on_fetch)
        monkeypatch.setattr(service, "FETCHER", scripted)
        return scripted

    yield install


# --- RESEARCH-01 ---------------------------------------------------------------------------------------------


def test_research_01_atomic_run_on_admitted_account_with_two_permitted_sources(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR, RAVI)
    sources = client.get(f"/api/v1/accounts/{account}/research-sources").json()
    eligible = {s["id"]: s for s in sources["items"]}
    assert set(eligible) == {str(org.source(JOHAR)), str(org.source(RAVI))}
    assert all(s["eligible"] and s["association"] == "alias_provenance" for s in eligible.values())
    created = start(client, operator, account, org.source(JOHAR), org.source(RAVI))
    assert created.status_code == 202, created.text
    run = created.json()
    assert (run["status"], run["extractor_version"], len(run["source_record_ids"])) == ("pending", "rules-1.0", 2)
    with db(app) as session:
        job = session.scalar(select(Job).where(Job.job_type == "research.run"))
        assert job is not None and job.payload_json == {"run_id": run["id"]}
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    detail = finished(app, client, run["id"])
    assert (detail["status"], detail["sources_processed"], detail["claims_proposed"]) == ("completed", 2, 10)
    assert {o["status"] for o in detail["observations"]} == {"processed"}


# --- RESEARCH-02 ---------------------------------------------------------------------------------------------


def test_research_02_excerpt_anchored_claims_review_into_source_supported_facts(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR, RAVI)
    detail = finished(app, client, start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"])
    claims = {(c["claim_type"], c["language"], str(c["value"])): c for c in detail["claims"]}
    english = claims[("campus_count", "en", "{'count': 2}")]
    assert english["excerpt"] == "We operate two campuses in Lahore, in Johar Town and DHA."
    assert english["excerpt_policy"] == "stored" and english["source"]["storage_class"] == "full_allowed"
    assert english["source"]["source_url"].startswith("https://school.fixture.example/")
    urdu = claims[("campus_count", "ur", "{'count': 3}")]
    assert urdu["excerpt"] is None and urdu["excerpt_policy"] == "locator_only"  # derived_only: no verbatim text
    assert urdu["locator"]["end"] > urdu["locator"]["start"] and len(urdu["span_sha256"]) == 64
    assert all(c["status"] == "proposed" for c in detail["claims"])
    assert count(app, AccountFact) == 0  # nothing is a fact until a reviewer accepts it

    accepted = review(client, operator, english, confidence_label="strong")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    review(client, operator, urdu)
    facts = {f["claim_type"] + str(f["value"]): f for f in client.get(f"/api/v1/accounts/{account}").json()["facts"]}
    fact = facts["campus_count{'count': 2}"]
    assert (fact["verification_status"], fact["confidence_label"]) == ("source_supported", "strong")
    assert fact["evidence_excerpt"] == "We operate two campuses in Lahore, in Johar Town and DHA."
    assert fact["source"]["provider"] == "fixture_lahore_schools"
    assert facts["campus_count{'count': 3}"]["evidence_excerpt"] is None
    with db(app) as session:
        audit = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "account.fact_added"))
        assert audit is not None and audit.details_json["origin"] == "research_review"


# --- RESEARCH-03 ---------------------------------------------------------------------------------------------


def test_research_03_evidence_never_crosses_between_similarly_named_campuses(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    johar = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    dha = org.account("Crescent Valley Grammar School (Synthetic)", "DHA Phase 5", DHA)
    crossed = start(client, operator, dha, org.source(JOHAR))
    assert crossed.status_code == 400 and "source_not_associated" in crossed.json()["error"]["message"]
    metadata_only = start(client, operator, dha, org.source(DHA))
    assert metadata_only.status_code == 400 and "metadata_only_no_content" in metadata_only.json()["error"]["message"]
    finished(app, client, start(client, operator, johar, org.source(JOHAR)).json()["id"])
    assert count(app, ResearchClaim, account_id=dha) == 0 and count(app, ResearchClaim, account_id=johar) == 6
    assert count(app, ResearchRun, account_id=dha) == 0


# --- RESEARCH-04 ---------------------------------------------------------------------------------------------


def test_research_04_abstains_on_injection_negation_and_absence(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    detail = finished(app, client, start(client, operator, account, org.source(JOHAR)).json()["id"])
    assert detail["usage"]["abstained"] == {"instruction_like_text": 1, "negated_statement": 1}
    types = {c["claim_type"] for c in detail["claims"]}
    assert types <= {"public_workflow_signal", "campus_count", "public_contact_channel"}
    assert not any(c["value"] == {"count": 40} for c in detail["claims"])
    assert not any("Excel" in str(c) or "SYSTEM" in str(c) for c in detail["claims"])
    phone = next(c for c in detail["claims"] if c["value"] == {"channel": "public_phone_listed"})
    assert "000-0000000" not in phone["excerpt"] and "[number]" in phone["excerpt"]


# --- RESEARCH-05 ---------------------------------------------------------------------------------------------


def test_research_05_revoked_or_expired_rights_store_and_publish_nothing(
    app: FastAPI, client: TestClient, org: Org, operator: str, clock: FixedClock
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    run_id = start(client, operator, account, org.source(JOHAR)).json()["id"]
    clock.advance(timedelta(days=60))  # past the source's provenance expiry, after scheduling
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    detail = finished(app, client, run_id)
    assert detail["observations"][0]["status"] == "skipped"
    assert detail["observations"][0]["reason_code"] == "source_rights_expired"
    assert detail["claims"] == [] and detail["status"] == "completed"

    clock.advance(timedelta(days=-60))
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    fresh = finished(app, client, start(client, operator, account, org.source(JOHAR)).json()["id"])
    claim = next(c for c in fresh["claims"] if c["claim_type"] == "campus_count")
    clock.advance(timedelta(days=60))
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    refused = review(client, operator, claim)
    assert refused.status_code == 409 and "source_rights_expired" in refused.json()["error"]["message"]
    rendered = client.get(f"/api/v1/research-runs/{fresh['id']}").json()
    withheld = next(c for c in rendered["claims"] if c["id"] == claim["id"])
    assert withheld["excerpt"] is None and withheld["excerpt_withheld_reason"] == "source_rights_expired"
    assert count(app, AccountFact) == 0
    with db(app) as session:  # derived-only text never reaches the database
        assert session.scalar(select(func.count()).select_from(ResearchClaim).where(
            ResearchClaim.storage_class != "full_allowed", ResearchClaim.excerpt.is_not(None))) == 0  # fmt: skip


# --- RESEARCH-06 ---------------------------------------------------------------------------------------------


def test_research_06_unsafe_documents_and_budgets_fail_safely(
    app: FastAPI, client: TestClient, org: Org, operator: str, fetcher: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR, RAVI)
    johar = f"fixture_lahore_schools:{JOHAR}"
    now = app.state.clock.now()
    cases = {
        "compressed_content_refused": documents.RawDocument("text/html", "gzip", b"\x1f\x8b" + b"\x00" * 100, now),
        "unsupported_media_type": documents.RawDocument("application/pdf", None, b"%PDF-1.7", now),
        "response_too_large": documents.RawDocument("text/plain", None, b"x" * (documents.MAX_BODY_BYTES + 1), now),
        "undecodable_body": documents.RawDocument("text/plain", None, b"\xff\xfe\xfd", now),
    }
    for reason, response in cases.items():
        fetcher({johar: response})
        detail = finished(app, client, start(client, operator, account, org.source(JOHAR)).json()["id"])
        assert (detail["status"], detail["error_code"], detail["claims"]) == ("failed", reason, []), reason

    elapsed = {"now": 0.0}
    monkeypatch.setattr(service, "MONOTONIC", lambda: elapsed["now"])

    def slow_fetch(seconds: float) -> Any:
        return lambda _key: elapsed.__setitem__("now", elapsed["now"] + seconds)

    fetcher({}, on_fetch=slow_fetch(31))  # each fetch takes 31 s of a 30 s per-source budget
    slow = finished(app, client, start(client, operator, account, org.source(JOHAR)).json()["id"])
    assert slow["observations"][0]["reason_code"] == "source_time_budget" and slow["claims"] == []

    scripted = fetcher({}, on_fetch=slow_fetch(61))  # the first source exhausts the 60 s job budget
    over = finished(app, client, start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"])
    assert (over["status"], over["partial_reason"]) == ("partial", "job_time_budget")
    assert len(scripted.calls) == 1  # the second source is never fetched

    website = _register_website_source(app, org, account)
    refused = start(client, operator, account, website)
    assert refused.status_code == 400 and "live_fetch_not_authorized" in refused.json()["error"]["message"]


def _register_website_source(app: FastAPI, org: Org, account: uuid.UUID) -> uuid.UUID:
    """A first-party website source registered via the P1.4 evidence path: provenance only, never fetched."""
    with db(app) as session:
        source = account_service.add_source_record(
            session, actor=org.actor, clock=app.state.clock, provider="first_party_website",
            source_url="https://crescent-valley.fixture.example/admissions", observed_at=app.state.clock.now(),
            storage_class="full_allowed", rights_policy_version="rights-2026-10-23", commit=True,
        )  # fmt: skip
        source_id = source.id
    with db(app) as session:
        account_service.add_alias(session, actor=org.actor, clock=app.state.clock, account_id=account,
                                  name="website alias", source_record_id=source_id)  # fmt: skip
    return source_id


# --- RESEARCH-07 ---------------------------------------------------------------------------------------------


def test_research_07_replay_stale_lease_and_redelivery_never_duplicate(
    app: FastAPI, client: TestClient, org: Org, operator: str, clock: FixedClock
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    first = start(client, operator, account, org.source(JOHAR), idem="same-research-1")
    again = start(client, operator, account, org.source(JOHAR), idem="same-research-1")
    assert (first.status_code, again.status_code, again.json()["replayed"]) == (202, 202, True)
    assert first.json()["id"] == again.json()["id"]
    other = org.account("Ravi Bank Public School (Synthetic)", "Shahdara", RAVI)
    assert start(client, operator, other, org.source(RAVI), idem="same-research-1").status_code == 409
    with db(app) as session:
        [stale] = runner.claim_due_jobs(session, worker_id="stalled", max_items=1, now=clock.now())
    clock.advance(timedelta(seconds=61))
    assert [o.status for o in worker(app, "rescuer").run_once()] == ["succeeded"]
    late = runner.execute(app.state.session_factory, stale, environment="test", now_fn=lambda _db: clock.now(),
                          rng=random.Random(1))  # fmt: skip
    assert late.status == "lease_lost"
    run_id = uuid.UUID(first.json()["id"])
    with db(app) as session:
        job = session.scalar(select(Job).where(Job.id == stale.id))
        assert job is not None
        from app.jobs import registry as job_registry  # noqa: PLC0415

        ctx = job_registry.JobContext(job.id, job.organization_id, 3, clock.now(), "test", 3)
        assert service.handle_research_job(session, ctx, job_registry.ResearchRunPayload(run_id=run_id))["skipped"]
    assert count(app, ResearchClaim, run_id=run_id) == 6 and count(app, ResearchObservation, run_id=run_id) == 1
    assert client.get(f"/api/v1/research-runs/{run_id}").json()["status"] == "completed"


def test_research_07_crash_mid_run_retries_without_duplicates(
    app: FastAPI, client: TestClient, org: Org, operator: str, fetcher: Any, clock: FixedClock
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR, RAVI)
    crashes = {"left": 1}

    def crash_once(source_key: str) -> None:
        if source_key.endswith(RAVI) and crashes["left"]:
            crashes["left"] -= 1
            raise RuntimeError("worker crashed after the first source committed")

    fetcher({}, on_fetch=crash_once)
    run_id = start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"]
    assert [o.status for o in worker(app).run_once()] == ["retry_wait"]
    assert client.get(f"/api/v1/research-runs/{run_id}").json()["status"] == "running"
    clock.advance(timedelta(minutes=5))
    assert [o.status for o in worker(app).run_once()] == ["succeeded"]
    detail = client.get(f"/api/v1/research-runs/{run_id}").json()
    assert (detail["status"], detail["claims_proposed"]) == ("completed", 10)
    assert count(app, ResearchClaim, run_id=uuid.UUID(run_id)) == 10  # the first source's claims were not doubled


# --- RESEARCH-08 ---------------------------------------------------------------------------------------------


def test_research_08_rate_limits_partial_and_cancellation_keep_true_status(
    app: FastAPI, client: TestClient, org: Org, operator: str, fetcher: Any
) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR, RAVI)
    ravi = f"fixture_lahore_schools:{RAVI}"
    fetcher({ravi: documents.DocumentError("rate_limited", retryable=True)})
    partial = finished(app, client, start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"])
    assert (partial["status"], partial["partial_reason"], partial["sources_failed"]) == ("partial", "rate_limited", 1)
    assert partial["claims_proposed"] == 6

    fetcher({f"fixture_lahore_schools:{JOHAR}": documents.DocumentError("unavailable", retryable=True),
             ravi: documents.DocumentError("unavailable", retryable=True)})  # fmt: skip
    failed = finished(app, client, start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"])
    assert (failed["status"], failed["error_code"], failed["claims"]) == ("failed", "unavailable", [])

    pending = start(client, operator, account, org.source(JOHAR)).json()["id"]
    cancelled = client.post(f"/api/v1/research-runs/{pending}/cancel", headers=mutation_headers(operator)).json()
    assert cancelled["status"] == "cancelled" and worker(app).run_once() == []

    holder: dict[str, str] = {}
    scripted = fetcher({}, on_fetch=lambda _key: client.post(f"/api/v1/research-runs/{holder['id']}/cancel",
                                                            headers=mutation_headers(operator)))  # fmt: skip
    holder["id"] = start(client, operator, account, org.source(JOHAR), org.source(RAVI)).json()["id"]
    racing = finished(app, client, holder["id"])
    assert racing["status"] == "cancelled" and len(scripted.calls) == 1  # no attempt after cancellation committed


# --- RESEARCH-09 ---------------------------------------------------------------------------------------------


def test_research_09_auth_roles_org_scope_csrf_and_review_races(app: FastAPI, client: TestClient, org: Org) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    body = {"source_record_ids": [str(org.source(JOHAR))], "idempotency_key": key()}
    url = f"/api/v1/accounts/{account}/research-runs"
    assert client.post(url, json=body).status_code == 401
    observer = logged_in(client, "observer@r.example")
    assert client.get(f"/api/v1/accounts/{account}/research-sources").status_code == 200
    assert client.post(url, json=body, headers=mutation_headers(observer)).status_code == 403
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    assert client.post(url, json=body).status_code == 403  # missing CSRF
    assert client.post(url, json={**body, "source_url": "http://169.254.169.254/"},
                       headers=mutation_headers(operator)).status_code == 422  # fmt: skip
    assert client.post(url, json={**body, "source_record_ids": [str(uuid.uuid4())] * 6},
                       headers=mutation_headers(operator)).status_code == 422  # fmt: skip
    detail = finished(app, client, client.post(url, json=body, headers=mutation_headers(operator)).json()["id"])
    claim = detail["claims"][0]

    other = Org(app, "Other Org", "o")
    foreign_client = TestClient(app, raise_server_exceptions=False)
    foreign = logged_in(foreign_client, "operator@o.example")
    assert foreign_client.get(f"/api/v1/research-runs/{detail['id']}").status_code == 404
    assert foreign_client.get(f"/api/v1/accounts/{account}/research-sources").status_code == 404
    assert review(foreign_client, foreign, claim).status_code == 404
    other_account = other.account("Other Fixture School", "Gulberg", JOHAR)
    assert start(foreign_client, foreign, other_account, org.source(JOHAR)).status_code == 400  # our source id

    client.cookies.clear()
    observer = logged_in(client, "observer@r.example")
    assert review(client, observer, claim).status_code == 403
    client.cookies.clear()
    operator = logged_in(client, "operator@r.example")
    results: list[int] = []
    barrier = threading.Barrier(2)

    def race(action: str) -> None:
        local = TestClient(app, raise_server_exceptions=False)
        token = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        results.append(review(local, token, claim, action).status_code)

    threads = [threading.Thread(target=race, args=(a,)) for a in ("accept", "reject")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [200, 409]
    assert count(app, AccountFact) <= 1
    with db(app) as session:
        reviewed = session.scalar(select(ActionAudit).where(ActionAudit.action_type == "research.claim_reviewed"))
        assert reviewed is not None and reviewed.target_id == account
        assert session.scalar(select(func.count()).select_from(User)) == 6


def test_research_09_review_replay_is_idempotent(app: FastAPI, client: TestClient, org: Org, operator: str) -> None:
    account = org.account("Crescent Valley Grammar School (Synthetic)", "Johar Town", JOHAR)
    claim = finished(app, client, start(client, operator, account, org.source(JOHAR)).json()["id"])["claims"][0]
    body = {"action": "accept", "expected_version": 1, "reason": REASON, "idempotency_key": "review-key-0001"}
    url = f"/api/v1/research-claims/{claim['id']}/review"
    first = client.post(url, json=body, headers=mutation_headers(operator)).json()
    again = client.post(url, json=body, headers=mutation_headers(operator)).json()
    assert (again["replayed"], again["fact_id"]) == (True, first["fact_id"]) and count(app, AccountFact) == 1
    changed = client.post(url, json={**body, "reason": "Different words"}, headers=mutation_headers(operator))
    assert changed.status_code == 409
