from datetime import UTC, datetime

import pytest

from app.core.clock import FixedClock

# Fixed instant for every test that needs "now": 2026-10-23 12:00 in Lahore.
FIXED_NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_NOW)
