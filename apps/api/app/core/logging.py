"""Structured JSON logging with redaction at the boundary.

Every record becomes one JSON line:
    {"ts", "level", "service", "env", "logger", "event", "request_id", "context", "error"}

Our own code logs a stable event name as the message and passes details as
`extra={"context": {...}}`. Context keys outside SAFE_CONTEXT_KEYS are
replaced with "[REDACTED]" (recursively), and every string, including
third-party messages and tracebacks, passes through `scrub_text`.
"""

import json
import logging
import re
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import current_request_id

REDACTED = "[REDACTED]"
MAX_STRING = 512
MAX_TRACEBACK = 4000
MAX_DEPTH = 5
MAX_ITEMS = 50

# Context keys whose values may be logged (still scrubbed). Everything else is redacted.
SAFE_CONTEXT_KEYS = frozenset(
    {
        "account_id",
        "attempt",
        "cancelled",
        "claimed",
        "count",
        "dead",
        "dependency",
        "dispatched",
        "duration_ms",
        "error_class",
        "error_code",
        "fact_id",
        "failed",
        "job_id",
        "job_type",
        "method",
        "oldest_due_seconds",
        "path",
        "pending",
        "queue",
        "reason",
        "retry_wait",
        "running",
        "settings",
        "status",
        "status_code",
        "succeeded",
        "undispatched_events",
    }
)

_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:password@host  ->  scheme://[REDACTED]@host
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@:]*:[^\s/@]*@"), r"\1" + REDACTED + "@"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer " + REDACTED),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|cookie|set-cookie|session)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    # Phone numbers: +92 3xx xxxxxxx, 03xxxxxxxxx, and generic international +<8-15 digits>.
    (re.compile(r"(?<![\w+])(?:\+?92[\s-]?|0)3\d{2}[\s-]?\d{7}(?!\d)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<![\w])\+\d[\d\s-]{7,16}\d(?!\d)"), "[REDACTED_PHONE]"),
)


def scrub_text(text: str, limit: int = MAX_STRING) -> str:
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        text = text[:limit] + "...[truncated]"
    return text


def redact(value: Any, key: str | None = None, depth: int = 0) -> Any:
    """Allowlist-based redaction of a context value; never raises."""
    if key is not None and key not in SAFE_CONTEXT_KEYS:
        return REDACTED
    if depth >= MAX_DEPTH:
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        items = list(value.items())[:MAX_ITEMS]
        return {str(k): redact(v, str(k), depth + 1) for k, v in items}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact(v, None, depth + 1) for v in list(value)[:MAX_ITEMS]]
    return scrub_text(type(value).__name__)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._format(record)
        except Exception as exc:  # a log line must never take the process down
            fallback = {"level": "error", "service": self.service, "event": "log.format_error"}
            return json.dumps({**fallback, "error_class": type(exc).__name__})

    def _format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "service": self.service,
            "env": self.environment,
            "logger": record.name,
            "event": scrub_text(record.getMessage()),
        }
        request_id = current_request_id()
        if request_id is not None:
            entry["request_id"] = request_id
        context = getattr(record, "context", None)
        if isinstance(context, Mapping) and context:
            entry["context"] = redact(context)
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            entry["error"] = {
                "class": type(exc).__name__,
                "traceback": scrub_text("".join(traceback.format_exception(exc)), MAX_TRACEBACK),
            }
        return json.dumps(entry, ensure_ascii=True, default=str)


def configure_logging(service: str, environment: str, level: str = "INFO") -> None:
    """Route all logging (ours and third-party) through one JSON handler on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, environment))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "rq.worker", "alembic"):
        library_logger = logging.getLogger(name)
        library_logger.handlers.clear()
        library_logger.propagate = True
    # Access lines would carry query strings; the API logs its own `http.request` event instead.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # A broken sink must not print the record (and its data) to stderr.
    logging.raiseExceptions = False
