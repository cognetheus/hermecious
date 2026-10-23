"""Time source. Code that needs "now" takes a Clock so tests can fix time.

All instants are timezone-aware UTC. Convert to BUSINESS_TZ only to present
or reason about local business time (blueprint §2: Asia/Karachi).
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Karachi")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that only moves when told to. For tests."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at += delta
