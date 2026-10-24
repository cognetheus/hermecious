"""Worker health (ADR-011): runner heartbeat AND queue database, deliberately not Redis."""

import time
from pathlib import Path

import pytest

from app.workers import worker


@pytest.fixture
def heartbeat_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "heartbeat"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", path)
    return path


def test_fresh_heartbeat_is_fresh(heartbeat_file: Path) -> None:
    worker.write_heartbeat()
    assert worker.heartbeat_is_fresh(time.time())
    assert worker.heartbeat_is_fresh(time.time() + worker.MAX_HEARTBEAT_AGE_SECONDS - 1)


def test_stale_missing_or_garbage_heartbeat_is_not_fresh(heartbeat_file: Path) -> None:
    assert not worker.heartbeat_is_fresh(time.time())  # missing
    worker.write_heartbeat()
    assert not worker.heartbeat_is_fresh(time.time() + worker.MAX_HEARTBEAT_AGE_SECONDS + 1)
    heartbeat_file.write_text("not-a-number")
    assert not worker.heartbeat_is_fresh(time.time())


def test_no_heartbeat_is_unhealthy(heartbeat_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert worker.healthcheck() == 1
    assert "no recent runner heartbeat" in capsys.readouterr().out


def test_unreachable_queue_database_is_unhealthy(
    heartbeat_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worker.write_heartbeat()
    monkeypatch.setenv("HERMECIOUS_ENV", "test")
    monkeypatch.setenv("HERMECIOUS_ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")  # nothing listens on port 1
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    assert worker.healthcheck() == 1
    assert "queue database unreachable (OperationalError)" in capsys.readouterr().out
