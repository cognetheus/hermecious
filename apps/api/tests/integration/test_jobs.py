"""P1.5 acceptance: JOB-01..JOB-10 with fault injection. Every test asserts final DATABASE state."""

import json
import random
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
import redis.exceptions
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.accounts.models import AccountAuditSnapshot, ActionAudit
from app.accounts.snapshots import request_account_snapshot
from app.auth.models import Role
from app.auth.service import Actor
from app.core.clock import FixedClock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.core.request_context import bound_request_id
from app.core.settings import Settings
from app.jobs import registry, runner
from app.jobs import service as jobs
from app.jobs.models import Job, OutboxEvent
from tests.integration.auth_helpers import add_organization, add_user, db, logged_in, mutation_headers
from tests.integration.lahore_fixtures import school_account

Logs = Callable[[], list[dict[str, Any]]]


@dataclass
class Org:
    actor: Actor
    account_id: uuid.UUID


def make_org(app: FastAPI, name: str = "Jobs Org", email: str = "owner@jobs.example") -> Org:
    org = add_organization(app, name)
    user = add_user(app, org, email, role=Role.OWNER)
    actor = Actor(user_id=user, organization_id=org, role=Role.OWNER, session_id=uuid.uuid4(), verifier="unused")
    return Org(actor=actor, account_id=school_account(app, actor).id)


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    session_factory: sessionmaker[Session] = app.state.session_factory
    return session_factory


@pytest.fixture
def org(app: FastAPI) -> Org:
    return make_org(app)


def clock_now(clock: FixedClock) -> Callable[[Session], datetime]:
    return lambda _db: clock.now()


def make_runner(
    factory: sessionmaker[Session],
    clock: FixedClock,
    *,
    sink: runner.NotificationSink | None = None,
    worker: str = "worker-a",
    seed: int = 7,
) -> runner.JobRunner:
    return runner.JobRunner(
        factory,
        worker_id=worker,
        environment="test",
        sink=sink or runner.NoSink(),
        wake_client=None,
        heartbeat=lambda: None,
        now_fn=clock_now(clock),
        rng=random.Random(seed),
    )


def request(app: FastAPI, org: Org, key: str = "snap-1", account_id: uuid.UUID | None = None) -> jobs.JobReceipt:
    with db(app) as session:
        receipt = request_account_snapshot(
            session,
            actor=org.actor,
            clock=app.state.clock,
            environment="test",
            account_id=account_id or org.account_id,
            idempotency_key=key,
        )
        session.commit()
        return receipt


def rows(app: FastAPI, model: type[Any]) -> list[Any]:
    with db(app) as session:
        return list(session.scalars(select(model)))


def count(app: FastAPI, model: type[Any]) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def job_row(app: FastAPI, job_id: uuid.UUID) -> Job:
    with db(app) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job


# --- JOB-01 / JOB-02 -----------------------------------------------------------------------------


def test_domain_change_job_and_outbox_commit_together(app: FastAPI, org: Org) -> None:
    with bound_request_id("req_job01_000000000000000001"):
        receipt = request(app, org)
    assert receipt.created and receipt.status == "pending"
    job = job_row(app, receipt.job_id)
    [event] = rows(app, OutboxEvent)
    audits = [a for a in rows(app, ActionAudit) if a.action_type == "account.snapshot_requested"]
    assert (job.organization_id, event.organization_id, audits[0].organization_id) == (org.actor.organization_id,) * 3
    assert job.correlation_id == "req_job01_000000000000000001" == audits[0].request_id
    assert (event.event_type, event.aggregate_id, event.idempotency_key) == ("job.enqueued", job.id, str(job.id))
    assert event.dispatched_at is None and job.payload_json == {"account_id": str(org.account_id)}


def test_exception_before_commit_leaves_no_job_event_or_audit(app: FastAPI, org: Org) -> None:
    with db(app) as session, pytest.raises(RuntimeError, match="injected"):
        request_account_snapshot(
            session,
            actor=org.actor,
            clock=app.state.clock,
            environment="test",
            account_id=org.account_id,
            idempotency_key="snap-rollback",
        )
        raise RuntimeError("injected failure before commit")
    assert count(app, Job) == count(app, OutboxEvent) == 0
    assert "account.snapshot_requested" not in [a.action_type for a in rows(app, ActionAudit)]


# --- JOB-03 / JOB-04 ------------------------------------------------------------------------------


def test_committed_job_without_notification_is_found_by_polling(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    receipt = request(app, org)  # producer "dies" here: nothing ever published a notification
    worker = make_runner(factory, clock)  # a freshly (re)started worker
    outcomes = worker.run_once()
    assert [o.status for o in outcomes] == ["succeeded"]
    assert worker.run_once() == []
    job = job_row(app, receipt.job_id)
    assert (job.status, job.attempts, job.lease_token) == ("succeeded", 1, None)
    [snapshot] = rows(app, AccountAuditSnapshot)
    assert snapshot.job_id == job.id and snapshot.fact_count == 0
    [event] = rows(app, OutboxEvent)
    assert event.dispatch_sink == "none" and event.dispatched_at is not None


def test_redis_down_does_not_strand_work_and_notification_retries_later(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock, app_settings: Settings
) -> None:
    receipt = request(app, org)
    dead_redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    outcomes = make_runner(factory, clock, sink=runner.RedisSink(dead_redis)).run_once()
    dead_redis.close()
    assert [o.status for o in outcomes] == ["succeeded"]
    [event] = rows(app, OutboxEvent)
    assert event.dispatched_at is None and event.attempts == 1 and event.last_error_class == "sink_unavailable"
    assert job_row(app, receipt.job_id).status == "succeeded"  # notify state is independent of processing

    clock.advance(timedelta(minutes=1))
    with Redis.from_url(str(app_settings.redis_url)) as live:
        make_runner(factory, clock, sink=runner.RedisSink(live)).run_once()
        assert live.lrange(runner.WAKE_KEY, 0, -1) == [str(event.id).encode()]  # ids only, no payloads
    [event] = rows(app, OutboxEvent)
    assert event.dispatch_sink == "redis" and event.dispatched_at is not None
    assert count(app, AccountAuditSnapshot) == 1


# --- JOB-05 -------------------------------------------------------------------------------------------


def test_racing_workers_claim_each_job_exactly_once(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    receipts = [request(app, org, key=f"race-{i}") for i in range(10)]
    barrier = threading.Barrier(3)
    outcomes: list[runner.Outcome] = []
    lock = threading.Lock()

    def work(name: str) -> None:
        worker = make_runner(factory, clock, worker=name)
        barrier.wait()
        for _ in range(5):
            done = worker.run_once()
            with lock:
                outcomes.extend(done)

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(str(o.job_id) for o in outcomes) == sorted(str(r.job_id) for r in receipts)
    assert all(o.status == "succeeded" for o in outcomes)
    assert all(j.attempts == 1 and j.status == "succeeded" for j in rows(app, Job))
    assert count(app, AccountAuditSnapshot) == 10


# --- JOB-06 --------------------------------------------------------------------------------------------


def test_idempotent_enqueue_and_payload_mismatch(app: FastAPI, org: Org) -> None:
    first = request(app, org, key="same-key")
    replay = request(app, org, key="same-key")
    assert (replay.job_id, replay.created) == (first.job_id, False)
    other_account = school_account(app, org.actor).id
    with pytest.raises(Conflict, match="different payload"):
        request(app, org, key="same-key", account_id=other_account)
    with db(app) as session, pytest.raises(InvalidRequest, match="not registered"):
        jobs.enqueue_job(
            session,
            organization_id=org.actor.organization_id,
            environment="test",
            job_type="account.audit_snapshot",
            schema_version=2,
            payload={"account_id": str(org.account_id)},
            idempotency_key="same-key",
            clock=app.state.clock,
        )
    assert count(app, Job) == count(app, OutboxEvent) == 1
    assert [a.action_type for a in rows(app, ActionAudit)].count("account.snapshot_requested") == 1


def test_concurrent_identical_enqueues_create_one_job(app: FastAPI, org: Org) -> None:
    barrier = threading.Barrier(4)
    receipts: list[jobs.JobReceipt] = []

    def attempt() -> None:
        barrier.wait()
        receipts.append(request(app, org, key="concurrent-key"))

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({r.job_id for r in receipts}) == 1 and sorted(r.created for r in receipts) == [False, False, False, True]
    assert count(app, Job) == count(app, OutboxEvent) == 1


def test_http_idempotency_key_contract(app: FastAPI, org: Org) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    csrf = logged_in(client, "owner@jobs.example")
    path = f"/api/v1/accounts/{org.account_id}/snapshots"
    headers = {**mutation_headers(csrf), "Idempotency-Key": "http-key-1"}
    first, again = client.post(path, headers=headers), client.post(path, headers=headers)
    assert first.status_code == again.status_code == 202
    assert first.json()["job_id"] == again.json()["job_id"] and (first.json()["created"], again.json()["created"]) == (
        True,
        False,
    )
    other = school_account(app, org.actor).id
    clash = client.post(f"/api/v1/accounts/{other}/snapshots", headers=headers)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "CONFLICT"
    assert client.post(path, headers=mutation_headers(csrf)).status_code == 422  # key is required
    bad = client.post(path, headers={**mutation_headers(csrf), "Idempotency-Key": "bad key!"})
    assert bad.status_code == 422
    status = client.get(f"/api/v1/jobs/{first.json()['job_id']}").json()
    assert status["status"] == "pending" and "payload" not in json.dumps(status)


# --- JOB-07 ---------------------------------------------------------------------------------------------


def test_crash_inside_the_effect_transaction_leaves_no_effect_and_reclaim_succeeds(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    receipt = request(app, org)
    with factory() as session:
        [claimed] = runner.claim_due_jobs(session, worker_id="doomed", max_items=1, now=clock.now())
    with factory() as session:  # effect written, process dies before commit/ack
        spec = registry.resolve(claimed.job_type, 1, "test")
        spec.handler(
            session,
            registry.JobContext(claimed.id, claimed.organization_id, 1, clock.now()),
            spec.payload_model.model_validate(claimed.payload),
        )
        session.flush()
    assert count(app, AccountAuditSnapshot) == 0  # never committed
    assert make_runner(factory, clock).run_once() == []  # lease still held by the dead worker
    clock.advance(runner.LEASE + timedelta(seconds=1))
    assert [o.status for o in make_runner(factory, clock, worker="rescuer").run_once()] == ["succeeded"]
    job = job_row(app, receipt.job_id)
    assert (job.status, job.attempts) == ("succeeded", 2)
    assert count(app, AccountAuditSnapshot) == 1


def test_committed_effect_without_ack_is_not_duplicated_and_stale_owner_is_fenced(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    receipt = request(app, org)
    with factory() as session:
        [stale] = runner.claim_due_jobs(session, worker_id="slow-worker", max_items=1, now=clock.now())
    with factory() as session:  # effect committed independently, then the worker stalls before ack
        spec = registry.resolve(stale.job_type, 1, "test")
        spec.handler(
            session,
            registry.JobContext(stale.id, stale.organization_id, 1, clock.now()),
            spec.payload_model.model_validate(stale.payload),
        )
        session.commit()
    clock.advance(runner.LEASE + timedelta(seconds=1))
    assert [o.status for o in make_runner(factory, clock, worker="new-owner").run_once()] == ["succeeded"]
    winner = job_row(app, receipt.job_id)

    with factory() as session, pytest.raises(runner.LeaseLost):  # the stale worker wakes up
        runner.complete_job(
            session, job_id=stale.id, lease_token=stale.lease_token, result_digest="0" * 64, now=clock.now()
        )
    with factory() as session:
        assert (
            runner.fail_job(
                session,
                job_id=stale.id,
                lease_token=stale.lease_token,
                error_class="late",
                retryable=True,
                now=clock.now(),
                rng=random.Random(1),
            )
            is None
        )
    final = job_row(app, receipt.job_id)
    assert (final.status, final.result_digest, final.attempts) == ("succeeded", winner.result_digest, 2)
    assert count(app, AccountAuditSnapshot) == 1  # UNIQUE(organization_id, job_id) absorbed the re-run


def test_expired_lease_on_last_attempt_goes_dead_not_silently_lost(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    receipt = request(app, org)
    with factory() as session:
        session.execute(select(Job))  # noqa: B018
        job = session.get(Job, receipt.job_id)
        assert job is not None
        job.max_attempts = 1
        session.commit()
    with factory() as session:
        runner.claim_due_jobs(session, worker_id="crashes", max_items=1, now=clock.now())
    clock.advance(runner.LEASE + timedelta(seconds=1))
    make_runner(factory, clock).run_once()
    dead = job_row(app, receipt.job_id)
    assert (dead.status, dead.last_error_class, dead.attempts) == ("dead", "lease_expired", 1)
    assert dead.finished_at is not None and count(app, AccountAuditSnapshot) == 0


# --- JOB-08 -----------------------------------------------------------------------------------------------


@pytest.fixture
def flaky(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Registers a test-only job type whose failures are scripted per call."""
    script: dict[str, Any] = {"failures": [], "calls": 0}

    def handler(db: Session, ctx: registry.JobContext, payload: registry.NoopPayload) -> dict[str, Any]:
        script["calls"] += 1
        if script["failures"]:
            raise script["failures"].pop(0)
        return {"ok": True}

    spec = registry.JobSpec(
        "diagnostic.flaky", 1, registry.NoopPayload, handler, max_attempts=3, environments=frozenset({"test"})
    )
    monkeypatch.setitem(registry.REGISTRY, ("diagnostic.flaky", 1), spec)
    yield script


def enqueue_flaky(app: FastAPI, org: Org, key: str = "flaky-1") -> uuid.UUID:
    with db(app) as session:
        receipt = jobs.enqueue_job(
            session,
            organization_id=org.actor.organization_id,
            environment="test",
            job_type="diagnostic.flaky",
            schema_version=1,
            payload={},
            idempotency_key=key,
            clock=app.state.clock,
        )
        session.commit()
        return receipt.job_id


def test_transient_failures_back_off_then_succeed(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock, flaky: dict[str, Any]
) -> None:
    flaky["failures"] = [registry.TransientJobError(), registry.TransientJobError("upstream_timeout")]
    job_id = enqueue_flaky(app, org)
    worker = make_runner(factory, clock)
    for attempt, base_seconds in [(1, 2), (2, 4)]:
        assert [o.status for o in worker.run_once()] == ["retry_wait"]
        job = job_row(app, job_id)
        delay = (job.available_at - clock.now()).total_seconds()
        assert base_seconds * 0.8 <= delay <= base_seconds * 1.2, (attempt, delay)
        assert worker.run_once() == []  # not due yet: no busy retry
        clock.advance(timedelta(seconds=base_seconds * 1.2 + 0.01))
    assert [o.status for o in worker.run_once()] == ["succeeded"]
    job = job_row(app, job_id)
    assert (job.status, job.attempts, job.last_error_class, flaky["calls"]) == ("succeeded", 3, None, 3)


def test_permanent_failure_is_dead_immediately(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock, flaky: dict[str, Any]
) -> None:
    flaky["failures"] = [registry.PermanentJobError("bad_input")]
    job_id = enqueue_flaky(app, org)
    assert [o.status for o in make_runner(factory, clock).run_once()] == ["dead"]
    job = job_row(app, job_id)
    assert (job.status, job.attempts, job.last_error_class) == ("dead", 1, "bad_input")
    clock.advance(timedelta(hours=1))
    assert make_runner(factory, clock).run_once() == [] and flaky["calls"] == 1


def test_retries_are_bounded_and_errors_are_sanitized(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock, flaky: dict[str, Any], json_logs: Logs
) -> None:
    flaky["failures"] = [RuntimeError("connect postgresql://u:job-secret-value@db/x password=hunter2")] * 5
    job_id = enqueue_flaky(app, org)
    worker = make_runner(factory, clock)
    statuses = []
    for _ in range(5):
        statuses += [o.status for o in worker.run_once()]
        clock.advance(runner.BACKOFF_CAP)
    assert statuses == ["retry_wait", "retry_wait", "dead"]
    job = job_row(app, job_id)
    assert (job.status, job.attempts, job.last_error_class) == ("dead", 3, "retries_exhausted")
    logs = json.dumps(json_logs())
    assert "job-secret-value" not in logs and "hunter2" not in logs
    assert "unexpected_error" in logs


# --- JOB-09 ------------------------------------------------------------------------------------------------


class RecordingSink:
    name = "redis"

    def __init__(self, fail: int = 0) -> None:
        self.seen: list[uuid.UUID] = []
        self.fail = fail
        self.lock = threading.Lock()

    def notify(self, event_id: uuid.UUID, event_type: str) -> None:
        with self.lock:
            if self.fail:
                self.fail -= 1
                raise redis.exceptions.ConnectionError("sink down")
            self.seen.append(event_id)


def publish(factory: sessionmaker[Session], clock: FixedClock, sink: Any, worker: str = "pub-a") -> dict[str, int]:
    return runner.publish_outbox(
        factory, worker_id=worker, sink=sink, max_items=50, now_fn=clock_now(clock), rng=random.Random(3)
    )


def test_racing_publishers_deliver_each_event_once(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    for i in range(8):
        request(app, org, key=f"evt-{i}")
    sink = RecordingSink()
    barrier = threading.Barrier(2)

    def go(name: str) -> None:
        barrier.wait()
        publish(factory, clock, sink, worker=name)

    threads = [threading.Thread(target=go, args=(n,)) for n in ("pub-a", "pub-b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = rows(app, OutboxEvent)
    assert sorted(sink.seen) == sorted(e.id for e in events) and len(set(sink.seen)) == 8
    assert all(e.dispatched_at is not None for e in events)
    assert all(j.status == "pending" for j in rows(app, Job))  # notified != processed


def test_failed_notification_is_retried_after_backoff_never_lost(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    request(app, org)
    sink = RecordingSink(fail=1)
    assert publish(factory, clock, sink) == {"dispatched": 0, "failed": 1}
    assert publish(factory, clock, sink) == {"dispatched": 0, "failed": 0}  # not due yet
    clock.advance(timedelta(seconds=3))
    assert publish(factory, clock, sink) == {"dispatched": 1, "failed": 0}
    [event] = rows(app, OutboxEvent)
    assert (event.attempts, event.last_error_class, len(sink.seen)) == (2, None, 1)


def test_publisher_crash_after_claim_is_recovered_after_lease_timeout(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    request(app, org)

    class CrashingSink:
        name = "redis"

        def notify(self, event_id: uuid.UUID, event_type: str) -> None:
            raise SystemExit("publisher process killed")

    with pytest.raises(SystemExit):
        publish(factory, clock, CrashingSink(), worker="dies")
    [event] = rows(app, OutboxEvent)
    assert event.dispatched_at is None and event.lease_owner == "dies"
    sink = RecordingSink()
    assert publish(factory, clock, sink, worker="pub-b") == {"dispatched": 0, "failed": 0}  # leased
    clock.advance(runner.OUTBOX_LEASE + timedelta(seconds=1))
    assert publish(factory, clock, sink, worker="pub-b") == {"dispatched": 1, "failed": 0}
    assert sink.seen == [event.id]


# --- JOB-10 -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job_type", "version", "payload", "environment", "message"),
    [
        ("os.system", 1, {}, "test", "not registered"),
        ("app.jobs.runner.execute", 1, {}, "test", "not registered"),
        ("account.audit_snapshot", 9, {"account_id": str(uuid.uuid4())}, "test", "not registered"),
        ("diagnostic.noop", 1, {"note": "x" * 20_000}, "test", "too large"),
        ("diagnostic.noop", 1, {"note": "password=hunter2"}, "test", "credentials or contact data"),
        ("diagnostic.noop", 1, {"note": "call 03001234567"}, "test", "credentials or contact data"),
        ("diagnostic.noop", 1, {"note": "mail head@school.example"}, "test", "credentials or contact data"),
        ("diagnostic.noop", 1, {"token": "abc"}, "test", "credential fields"),
        ("diagnostic.noop", 1, {"note": "ok", "extra": 1}, "test", "does not match"),
        ("diagnostic.noop", 1, {"note": "ok"}, "production", "not enabled in this environment"),
        ("account.audit_snapshot", 1, {"account_id": "not-a-uuid"}, "test", "does not match"),
    ],
    ids=[
        "shell-name",
        "function-path",
        "unknown-version",
        "oversized",
        "password",
        "phone",
        "email",
        "secret-key",
        "extra-field",
        "noop-in-production",
        "bad-uuid",
    ],
)
def test_malicious_or_unsupported_payloads_fail_closed(
    app: FastAPI, org: Org, job_type: str, version: int, payload: dict[str, Any], environment: str, message: str
) -> None:
    with db(app) as session, pytest.raises(InvalidRequest, match=message):
        jobs.enqueue_job(
            session,
            organization_id=org.actor.organization_id,
            environment=environment,
            job_type=job_type,
            schema_version=version,
            payload=payload,
            idempotency_key="bad-1",
            clock=app.state.clock,
        )
    assert count(app, Job) == count(app, OutboxEvent) == 0


def test_cross_org_enqueue_read_and_injected_job_fail_closed(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    other = make_org(app, "Other Org", "owner@other.example")
    with pytest.raises(NotFound):
        request(app, org, key="cross", account_id=other.account_id)
    mine = request(app, org, key="mine")
    client = TestClient(app, raise_server_exceptions=False)
    logged_in(client, "owner@other.example")
    assert client.get(f"/api/v1/jobs/{mine.job_id}").status_code == 404
    with db(app) as session:  # raw injection: org A job pointing at org B's account
        injected = jobs.enqueue_job(
            session,
            organization_id=org.actor.organization_id,
            environment="test",
            job_type="account.audit_snapshot",
            schema_version=1,
            payload={"account_id": str(other.account_id)},
            idempotency_key="injected",
            clock=clock,
        )
        session.commit()
    make_runner(factory, clock).run_once()
    dead = job_row(app, injected.job_id)
    assert (dead.status, dead.last_error_class) == ("dead", "account_not_found")
    assert [s.account_id for s in rows(app, AccountAuditSnapshot)] == [org.account_id]


def test_ops_diagnostics_are_owner_only_scoped_and_payload_free(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock, flaky: dict[str, Any]
) -> None:
    flaky["failures"] = [registry.PermanentJobError("bad_input")]
    enqueue_flaky(app, org)
    request(app, org, key="pending-one")
    worker = make_runner(factory, clock)
    worker.run_once()
    add_user(app, org.actor.organization_id, "operator@jobs.example", role=Role.OPERATOR)
    operator = TestClient(app, raise_server_exceptions=False)
    logged_in(operator, "operator@jobs.example")
    assert operator.get("/api/v1/ops/jobs").status_code == 403
    owner = TestClient(app, raise_server_exceptions=False)
    logged_in(owner, "owner@jobs.example")
    body = owner.get("/api/v1/ops/jobs").json()
    assert body["metrics"]["dead"] == 1 and body["metrics"]["succeeded"] == 1
    assert [d["last_error_class"] for d in body["dead"]] == ["bad_input"]
    assert "payload" not in json.dumps(body) and str(org.account_id) not in json.dumps(body)


def test_notification_backoff_grows_per_failed_delivery(
    app: FastAPI, org: Org, factory: sessionmaker[Session], clock: FixedClock
) -> None:
    """Regression (found in the real-container run): retries must back off exponentially, not every 2s."""
    request(app, org)
    sink = RecordingSink(fail=10)
    delays = []
    for _ in range(4):
        publish(factory, clock, sink)
        [event] = rows(app, OutboxEvent)
        delays.append((event.next_attempt_at - clock.now()).total_seconds())
        clock.advance(event.next_attempt_at - clock.now() + timedelta(milliseconds=1))
    for delay, base in zip(delays, [2, 4, 8, 16], strict=True):  # first failure = attempt 1 -> 2s base
        assert base * 0.8 <= delay <= base * 1.2, delays


# --- Lease heartbeat (2026-10-25 audit decision) ------------------------------------------------------------------


def test_lease_heartbeat_extends_only_our_lease_and_stops_a_superseded_worker(
    factory: sessionmaker[Session], clock: FixedClock, org: Org
) -> None:
    with factory() as session:
        jobs.enqueue_job(
            session, organization_id=org.actor.organization_id, environment="test", job_type="diagnostic.noop",
            schema_version=1, payload={"note": "lease"}, idempotency_key="lease-heartbeat-0001", clock=clock,
        )  # fmt: skip
        session.commit()
    with factory() as session:
        (claimed,) = runner.claim_due_jobs(session, worker_id="worker-a", max_items=1, now=clock.now())
    clock.advance(timedelta(seconds=50))  # a long step: the lease (60 s) is nearly gone
    assert runner.renew_lease(factory, claimed.id, claimed.lease_token, clock_now(clock)) is True
    with factory() as session:
        job = session.get(Job, claimed.id)
        assert job is not None and job.lease_expires_at == clock.now() + runner.LEASE
    stale = runner.renew_lease(factory, claimed.id, uuid.uuid4(), clock_now(clock))
    assert stale is False  # someone else's token never extends the lease
    ctx = registry.JobContext(claimed.id, org.actor.organization_id, 1, clock.now(), "test", 3, lambda: False)
    with pytest.raises(registry.LeaseLostError):
        registry.keep_alive(ctx)
    registry.keep_alive(registry.JobContext(claimed.id, org.actor.organization_id, 1, clock.now()))  # no-op
