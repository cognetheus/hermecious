from datetime import UTC, datetime, timedelta

import pytest

from app.core.clock import BUSINESS_TZ, FixedClock, SystemClock


def test_fixed_clock_is_utc_and_stable(clock: FixedClock) -> None:
    assert clock.now() == clock.now() == datetime(2026, 10, 23, 7, 0, tzinfo=UTC)
    assert clock.now().utcoffset() == timedelta(0)


def test_fixed_clock_business_time_is_karachi(clock: FixedClock) -> None:
    local = clock.now().astimezone(BUSINESS_TZ)
    assert local.isoformat() == "2026-10-23T12:00:00+05:00"


def test_fixed_clock_advances_only_when_told(clock: FixedClock) -> None:
    clock.advance(timedelta(hours=13))
    assert clock.now().astimezone(BUSINESS_TZ).date().isoformat() == "2026-10-24"


def test_fixed_clock_normalizes_offsets_to_utc() -> None:
    karachi_noon = datetime(2026, 10, 23, 12, 0, tzinfo=BUSINESS_TZ)
    assert FixedClock(karachi_noon).now() == datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


def test_fixed_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 10, 23, 7, 0))  # noqa: DTZ001


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().tzinfo is UTC
