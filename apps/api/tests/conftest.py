import io
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.logging import JsonFormatter

# Fixed instant for every test that needs "now": 2026-10-23 12:00 in Lahore.
FIXED_NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_NOW)


@pytest.fixture
def json_logs() -> Iterator[Callable[[], list[dict[str, Any]]]]:
    """Capture everything logged during the test as parsed JSON lines (production formatter)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("test", "test"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
