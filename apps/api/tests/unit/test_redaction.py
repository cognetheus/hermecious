"""A6/A8: secrets and personal data never reach log output; log lines cannot be forged."""

import json
import logging
from collections.abc import Callable
from typing import Any

import pytest

from app.core.logging import REDACTED, JsonFormatter, redact, scrub_text

Logs = Callable[[], list[dict[str, Any]]]

SEEDED = {
    "password": "hunter2-pass-value",
    "api_key": "sk-test-api-key-value-0123456789",
    "cookie": "hermecious_session=cookie-value-abc",
    "db_url": "postgresql://app:db-pass-value@postgres:5432/app",
    "phone": "+92 300 1234567",
    "message_body": "Assalam o alaikum, my number is 03001234567",
    "email": "principal@school.example",
}
SECRET_VALUES = [
    "hunter2-pass-value",
    "sk-test-api-key-value-0123456789",
    "cookie-value-abc",
    "db-pass-value",
    "300 1234567",
    "03001234567",
    "principal@school.example",
    "Assalam",
]


def test_nested_context_redacts_every_seeded_value(json_logs: Logs) -> None:
    context = {
        "status": 200,
        "nested": {"headers": {"authorization": "Bearer abc.def.ghi", **SEEDED}},
        "items": [SEEDED, {"deeper": [SEEDED]}],
        **SEEDED,
    }
    logging.getLogger("test").info("test.event", extra={"context": context})
    [entry] = json_logs()
    text = json.dumps(entry)
    for value in SECRET_VALUES:
        assert value not in text
    assert entry["context"]["status"] == 200
    assert entry["context"]["password"] == REDACTED
    assert entry["context"]["nested"] == REDACTED


def test_allowed_keys_still_have_their_strings_scrubbed(json_logs: Logs) -> None:
    logging.getLogger("test").info(
        "test.event",
        extra={"context": {"reason": "connect to postgresql://u:db-pass-value@h/db failed for +92 300 1234567"}},
    )
    [entry] = json_logs()
    assert entry["context"]["reason"] == "connect to postgresql://[REDACTED]@h/db failed for [REDACTED_PHONE]"


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ("could not connect to postgresql://app:db-pass-value@postgres/app", "db-pass-value"),
        ("Authorization: Bearer eyJhbGciOi.payload.sig", "eyJhbGciOi"),
        ("password=hunter2-pass-value user=app", "hunter2-pass-value"),
        ("token: 'tok-value-123'", "tok-value-123"),
        ("Cookie: hermecious_session=sess-value", "sess-value"),
        ("reply from 0300-1234567 and +923001234567", "1234567"),
        ("contact admissions@school.example", "admissions@school.example"),
        ("international +44 20 7946 0958", "7946"),
    ],
)
def test_free_text_messages_are_scrubbed(text: str, leak: str, json_logs: Logs) -> None:
    logging.getLogger("thirdparty.lib").warning(text)
    [entry] = json_logs()
    assert leak not in entry["event"]


def test_percent_args_are_scrubbed_after_formatting(json_logs: Logs) -> None:
    logging.getLogger("thirdparty.lib").error("connecting to %s", "redis://:redis-pass-value@redis:6379/0")
    [entry] = json_logs()
    assert "redis-pass-value" not in entry["event"]


def test_exception_tracebacks_are_scrubbed(json_logs: Logs) -> None:
    try:
        raise RuntimeError("failed with postgresql://app:db-pass-value@postgres/app")
    except RuntimeError:
        logging.getLogger("test").exception("test.failed")
    [entry] = json_logs()
    assert entry["error"]["class"] == "RuntimeError"
    assert "db-pass-value" not in entry["error"]["traceback"]
    assert "postgresql://[REDACTED]@postgres/app" in entry["error"]["traceback"]


def test_newlines_cannot_forge_a_second_log_line(json_logs: Logs) -> None:
    forged = 'ok\n{"level":"info","event":"auth.login_succeeded","service":"api"}'
    logging.getLogger("test").info(forged, extra={"context": {"reason": forged}})
    lines = json_logs()
    assert len(lines) == 1
    assert lines[0]["event"].startswith("ok\n")


def test_oversized_and_deep_values_are_bounded() -> None:
    assert scrub_text("x" * 10_000).endswith("...[truncated]")
    assert len(scrub_text("x" * 10_000)) < 600
    deep: dict[str, Any] = {"status": 1}
    for _ in range(10):
        deep = {"status": deep}
    assert "REDACTED" in json.dumps(redact(deep))
    many = {"status": list(range(1_000))}
    assert len(redact(many)["status"]) == 50


def test_unserializable_and_hostile_objects_do_not_break_logging(json_logs: Logs) -> None:
    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

        def __str__(self) -> str:
            raise RuntimeError("boom")

    logging.getLogger("test").info("test.event", extra={"context": {"status": Hostile()}})
    [entry] = json_logs()
    assert entry["context"]["status"] == "Hostile"


def test_entry_has_contract_fields(json_logs: Logs) -> None:
    logging.getLogger("app.test").info("test.event")
    [entry] = json_logs()
    assert set(entry) >= {"ts", "level", "service", "env", "logger", "event"}
    assert entry["ts"].endswith("Z")
    assert entry["level"] == "info"


def test_formatter_never_raises() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "%s %s", ("only-one",), None)
    line = json.loads(JsonFormatter("api", "test").format(record))
    assert line["event"] == "log.format_error"
