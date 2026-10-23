"""API readiness and worker health against the real test Postgres and Redis."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Worker

from app.core.settings import Settings
from app.main import create_app
from app.workers import worker as worker_module


def test_ready_with_real_dependencies(settings: Settings) -> None:
    response = TestClient(create_app(settings)).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


def test_worker_healthcheck_tracks_real_registration(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name_file = tmp_path / "worker-name"
    name_file.write_text("hermecious-integration-test")
    monkeypatch.setattr(worker_module, "NAME_FILE", name_file)
    connection = Redis.from_url(str(settings.redis_url))
    rq_worker = Worker(["default"], connection=connection, name="hermecious-integration-test")

    assert worker_module.healthcheck() == 1  # not registered yet
    rq_worker.register_birth()  # type: ignore[no-untyped-call]  # rq leaves this unannotated
    try:
        assert worker_module.healthcheck() == 0
    finally:
        rq_worker.register_death()  # type: ignore[no-untyped-call]
        connection.delete(rq_worker.key)
    assert worker_module.healthcheck() == 1
