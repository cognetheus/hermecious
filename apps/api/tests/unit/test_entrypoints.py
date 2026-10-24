"""A5: invalid config stops the API and worker with a structured event naming settings, never values."""

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app import __main__ as api_main
from app.workers import worker as worker_module


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = False


@pytest.mark.parametrize(("entrypoint", "service"), [(api_main.main, "api"), (worker_module.run, "worker")])
def test_invalid_config_logs_names_only(
    entrypoint: Callable[[], int],
    service: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(worker_module, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    monkeypatch.delenv("HERMECIOUS_ENV", raising=False)
    monkeypatch.delenv("HERMECIOUS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "mysql://app:db-secret-value@db/app")
    monkeypatch.setenv("REDIS_URL", "")
    assert entrypoint() == 1
    out = capsys.readouterr().out
    [line] = [json.loads(raw) for raw in out.splitlines()]
    assert line["event"] == "config.invalid"
    assert line["level"] == "critical"
    assert line["service"] == service
    assert line["context"] == {
        "settings": ["DATABASE_URL", "HERMECIOUS_ALLOWED_ORIGINS", "HERMECIOUS_ENV", "REDIS_URL"]
    }
    assert "db-secret-value" not in out and "mysql://" not in out
