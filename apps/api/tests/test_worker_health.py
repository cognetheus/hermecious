from datetime import UTC, datetime, timedelta

from app.workers import worker
from app.workers.worker import MAX_HEARTBEAT_AGE, heartbeat_is_fresh

AT = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


def test_recent_heartbeat_is_fresh() -> None:
    assert heartbeat_is_fresh(AT - timedelta(seconds=5), AT)
    assert heartbeat_is_fresh(AT - MAX_HEARTBEAT_AGE, AT)


def test_stale_or_missing_heartbeat_is_not_fresh() -> None:
    assert not heartbeat_is_fresh(AT - MAX_HEARTBEAT_AGE - timedelta(seconds=1), AT)
    assert not heartbeat_is_fresh(None, AT)


def test_unregistered_worker_is_unhealthy(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(worker, "NAME_FILE", tmp_path / "absent")
    assert worker.healthcheck() == 1
    assert "not registered" in capsys.readouterr().out


def test_unreachable_broker_is_unhealthy(tmp_path, monkeypatch, capsys) -> None:
    name_file = tmp_path / "name"
    name_file.write_text("hermecious-test")
    monkeypatch.setattr(worker, "NAME_FILE", name_file)
    monkeypatch.setattr(worker, "HEALTHCHECK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    # Port 1 on loopback refuses connections immediately: Redis is "down".
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert worker.healthcheck() == 1
    assert "broker unreachable (ConnectionError)" in capsys.readouterr().out
