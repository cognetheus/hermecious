"""Discovery source-adapter contracts (P2.1). Versioned, typed, offline-first.

`fetch` takes a provider-scoped `source_key`, never a URL: there is no
arbitrary-egress operation in this interface (ADR-012). All adapter output is
untrusted data; it is validated here and never interpreted as instructions.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

CONTRACT_VERSION = "source-adapter-v1"

ShortText = Annotated[str, Field(min_length=1, max_length=250)]
Keyword = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[\w .'-]+$")]
SourceKey = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")]
StorageClassName = Literal["metadata_only", "derived_only", "full_allowed"]


class Operation(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    STORE_METADATA = "store_metadata"
    STORE_DERIVED = "store_derived"
    STORE_FULL = "store_full"


STORE_OPERATION: dict[str, Operation] = {
    "metadata_only": Operation.STORE_METADATA,
    "derived_only": Operation.STORE_DERIVED,
    "full_allowed": Operation.STORE_FULL,
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceQuery(_Strict):
    city: ShortText
    vertical_slug: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")]
    area: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    keywords: list[Keyword] = Field(default_factory=list, max_length=5)


class SourceCandidate(_Strict):
    provider: ShortText
    external_key: SourceKey | None
    display_name: ShortText
    city: ShortText
    vertical_slug: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")]
    locality: Annotated[str, Field(max_length=160)] | None = None
    source_url: Annotated[str, Field(max_length=2048)] | None = None
    observed_at: AwareDatetime
    # Unverified hints only: never facts, never instructions.
    claim_hints: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=5)


class SourceObservation(_Strict):
    provider: ShortText
    external_key: SourceKey | None
    observed_at: AwareDatetime
    source_url: Annotated[str, Field(max_length=2048)] | None = None
    permitted_storage_class: StorageClassName
    rights_policy_version: Annotated[str, Field(min_length=1, max_length=80)]
    expires_at: AwareDatetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SourcePage(_Strict):
    candidates: list[SourceCandidate]
    next_cursor: Annotated[str, Field(max_length=512)] | None = None
    reported_cost_units: Annotated[int, Field(ge=0, le=1000)] = 0


class SourceDescriptor(_Strict):
    """Operator-reviewed policy for one provider. Missing review/terms/rights disables it."""

    provider: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
    adapter_version: Annotated[str, Field(min_length=1, max_length=40)]
    source_kind: Literal["fixture", "seed_list", "api", "website"]
    terms_reference: Annotated[str, Field(max_length=300)] | None  # a policy id, not necessarily a URL
    rights_policy_version: Annotated[str, Field(max_length=80)] | None
    permitted_operations: frozenset[Operation]
    max_storage_class: StorageClassName
    retention_ttl: timedelta
    request_quota: Annotated[int, Field(ge=0, le=1000)]
    result_limit: Annotated[int, Field(ge=0, le=1000)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    allowed_hostnames: frozenset[str]
    allow_http: bool = False
    requires_credentials: bool
    enabled: bool
    environments: frozenset[str]
    last_reviewed_at: datetime | None
    supported_cities: frozenset[str]
    supported_verticals: frozenset[str]


class SourceAdapter(Protocol):
    """Synchronous by convention (the API and worker runtime are synchronous).

    Adapters return raw provider-shaped mappings; adapters are untrusted, so the
    framework validates every page and record into `SourcePage`/`SourceCandidate`/
    `SourceObservation` itself and rejects bad records individually.
    """

    @property
    def descriptor(self) -> SourceDescriptor: ...

    def search(self, *, query: SourceQuery, limit: int, cursor: str | None = None) -> Mapping[str, Any]: ...

    def fetch(self, *, source_key: str) -> Mapping[str, Any]: ...


class AdapterTransientError(Exception):
    """Retryable within budget (rate limit, timeout)."""

    reason = "transient"


class AdapterRateLimited(AdapterTransientError):
    reason = "rate_limited"


class AdapterTimeout(AdapterTransientError):
    reason = "timeout"
