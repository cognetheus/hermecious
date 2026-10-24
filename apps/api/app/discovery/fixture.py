"""Offline synthetic adapter `fixture_lahore_schools` (P2.1). Makes no network requests.

Reads a versioned, internally authored dataset. Test-only `FixtureFaults`
simulate provider misbehaviour (429s, timeouts, cursor cycles, oversized or
duplicated pages, malformed records, bulk results) without any I/O.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from app.discovery.contracts import AdapterRateLimited, AdapterTimeout, SourceDescriptor, SourceQuery
from app.discovery.registry import DESCRIPTORS, FIXTURE_PROVIDER, FIXTURE_RIGHTS_POLICY

DATASET = Path(__file__).with_name("fixtures") / "lahore_schools_v1.json"


@cache
def load_dataset() -> Mapping[str, Any]:
    data: Mapping[str, Any] = json.loads(DATASET.read_text(encoding="utf-8"))
    return data


@dataclass(frozen=True)
class FixtureFaults:
    rate_limited_calls: frozenset[int] = frozenset()  # 1-based search call numbers that answer 429
    timeout_calls: frozenset[int] = frozenset()
    fetch_timeout_keys: frozenset[str] = frozenset()
    repeat_cursor: bool = False
    oversize_by: int = 0
    duplicate_first: bool = False
    extra_records: int = 0
    malformed: bool = False
    on_call: Callable[[], None] = field(default=lambda: None)  # e.g. advance a fake clock


class FixtureLahoreSchoolsAdapter:
    def __init__(self, descriptor: SourceDescriptor | None = None, faults: FixtureFaults | None = None) -> None:
        self._descriptor = descriptor or DESCRIPTORS[FIXTURE_PROVIDER]
        self.faults = faults or FixtureFaults()
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    def _records(self) -> list[dict[str, Any]]:
        records = [dict(r) for r in load_dataset()["records"]]
        for i in range(self.faults.extra_records):
            records.append(
                {
                    "key": f"bulk-{i:03d}",
                    "display_name": f"Bulk Synthetic School {i:03d} (Synthetic)",
                    "city": "Lahore",
                    "vertical": "schools",
                    "locality": "Bulk Town",
                    "source_url": f"https://school.fixture.example/bulk/{i}",
                    "storage_class": "metadata_only",
                    "observed_at": "2026-10-20T06:00:00Z",
                    "expires_at": None,
                    "claim_hints": [],
                    "data": {},
                }
            )
        if self.faults.malformed:
            records += [
                {"key": None, "display_name": "No Key School (Synthetic)", "city": "Lahore", "vertical": "schools"},
                {
                    "key": "naive-time",
                    "display_name": "Naive Time School (Synthetic)",
                    "city": "Lahore",
                    "vertical": "schools",
                    "observed_at": "2026-10-20T06:00:00",
                },
                {"key": "not-an-object"} | {"display_name": ["not", "a", "string"]},
                {
                    "key": "bad-url",
                    "display_name": "Bad Url School (Synthetic)",
                    "city": "Lahore",
                    "vertical": "schools",
                    "observed_at": "2026-10-20T06:00:00Z",
                    "source_url": "https://school.fixture.example/x#frag",
                },
            ]
        return records

    @staticmethod
    def _candidate(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "provider": FIXTURE_PROVIDER,
            "external_key": record.get("key"),
            "display_name": record.get("display_name"),
            "city": record.get("city"),
            "vertical_slug": record.get("vertical"),
            "locality": record.get("locality"),
            "source_url": record.get("source_url"),
            "observed_at": record.get("observed_at"),
            "claim_hints": record.get("claim_hints", []),
        }

    def search(self, *, query: SourceQuery, limit: int, cursor: str | None = None) -> dict[str, Any]:
        self.search_calls += 1
        self.faults.on_call()
        if self.search_calls in self.faults.rate_limited_calls:
            raise AdapterRateLimited()
        if self.search_calls in self.faults.timeout_calls:
            raise AdapterTimeout()
        records = self._records()
        offset = int(cursor.removeprefix("offset:")) if cursor and cursor.startswith("offset:") else 0
        size = limit + self.faults.oversize_by
        page = records[offset : offset + size]
        if self.faults.duplicate_first and page:
            page = [page[0], *page]
        next_offset = offset + limit
        next_cursor = None if next_offset >= len(records) else f"offset:{next_offset}"
        if self.faults.repeat_cursor:
            next_cursor = "offset:0"
        return {
            "candidates": [self._candidate(r) for r in page],
            "next_cursor": next_cursor,
            "reported_cost_units": 1,
        }

    def fetch(self, *, source_key: str) -> dict[str, Any]:
        self.fetch_calls += 1
        self.faults.on_call()
        if source_key in self.faults.fetch_timeout_keys:
            raise AdapterTimeout()
        record = next((r for r in self._records() if r.get("key") == source_key), None)
        if record is None:
            raise KeyError(source_key)
        return {
            "provider": FIXTURE_PROVIDER,
            "external_key": record["key"],
            "observed_at": record.get("observed_at"),
            "source_url": record.get("source_url"),
            "permitted_storage_class": record.get("storage_class"),
            "rights_policy_version": FIXTURE_RIGHTS_POLICY,
            "expires_at": record.get("expires_at"),
            "data": record.get("data", {}),
        }
