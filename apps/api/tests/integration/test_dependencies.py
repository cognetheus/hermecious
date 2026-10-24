"""API readiness and worker health against the real test Postgres and Redis."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import close_app, create_app
from app.workers import worker as worker_module


def test_ready_with_real_dependencies(settings: Settings) -> None:
    app = create_app(settings)
    response = TestClient(app).get("/health/ready")
    close_app(app)
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_worker_health_needs_heartbeat_and_real_database_not_redis(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_module, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    assert worker_module.healthcheck() == 1  # no heartbeat yet
    worker_module.write_heartbeat()
    assert worker_module.healthcheck() == 0  # real Postgres reachable
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # Redis down must not matter
    assert worker_module.healthcheck() == 0


def test_runner_loop_drains_a_job_heartbeats_and_stops(app_settings: Settings, app: Any) -> None:
    import threading

    from app.jobs import service as jobs
    from app.jobs.models import Job
    from app.jobs.runner import JobRunner, NoSink
    from tests.integration.auth_helpers import add_organization

    org = add_organization(app)
    factory = app.state.session_factory
    with factory() as session:
        receipt = jobs.enqueue_job(
            session,
            organization_id=org,
            environment="test",
            job_type="diagnostic.noop",
            schema_version=1,
            payload={},
            idempotency_key="loop-1",
            clock=app.state.clock,
        )
        session.commit()
    beats: list[int] = []
    stop = threading.Event()

    def heartbeat() -> None:
        beats.append(1)
        if len(beats) >= 2:
            stop.set()

    JobRunner(
        factory,
        worker_id="loop-test",
        environment="test",
        sink=NoSink(),
        wake_client=None,
        heartbeat=heartbeat,
        poll_seconds=1,
    ).run_forever(stop)
    with factory() as session:
        job = session.get(Job, receipt.job_id)
        assert job is not None and job.status == "succeeded"
    assert len(beats) == 2


def test_runner_waits_unhealthy_instead_of_crashing_before_migrations(settings: Settings) -> None:
    import threading

    from app.jobs.runner import JobRunner, NoSink
    from app.persistence.db import make_engine, make_session_factory
    from tests.integration.db import plain, scratch_database

    with scratch_database(str(settings.database_url), "unmigrated") as url:
        engine = make_engine(plain(url))
        stop = threading.Event()
        beats: list[int] = []
        timer = threading.Timer(2.5, stop.set)
        timer.start()
        JobRunner(
            make_session_factory(engine),
            worker_id="early",
            environment="test",
            sink=NoSink(),
            wake_client=None,
            heartbeat=lambda: beats.append(1),
            poll_seconds=1,
        ).run_forever(stop)  # returns when stopped; must not raise
        timer.cancel()
        engine.dispose()
    assert beats == []  # never reported healthy against an unmigrated schema
