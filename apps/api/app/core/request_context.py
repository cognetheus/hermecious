"""Correlation ID for the current HTTP request or worker job.

A client may supply an ID only if it is short and uses a safe charset;
anything else is replaced, so IDs can neither forge log lines nor grow
payloads. The context is always reset when the request or job ends.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id(prefix: str = "req") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def accept_request_id(candidate: str | None, prefix: str = "req") -> str:
    """Return `candidate` if it is a safe ID, else a fresh one."""
    if candidate is not None and _VALID_ID.fullmatch(candidate):
        return candidate
    return new_request_id(prefix)


def current_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def bound_request_id(request_id: str) -> Iterator[str]:
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)
