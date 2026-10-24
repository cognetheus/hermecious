"""OpenStreetMap Overpass school listings (P2.2, ADR-013). Disabled unless the owner reviews rights.

One fixed, parameterized query per run: `nwr["amenity"="school"](bbox); out center N`.
Only allowlisted tags are kept; contributor metadata is never requested. A
way/relation `center` is a representative point, not a verified address.
Listings are unverified map data, not prospects: no ownership, size, software
or buying signals are inferred.
"""

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.core.settings import Settings
from app.discovery.area import BBox, parse_bbox
from app.discovery.contracts import (
    AdapterRateLimited,
    AdapterResponseTooLarge,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterUpstreamError,
    Operation,
    SourceDescriptor,
    SourceQuery,
)
from app.egress.https_client import (
    EgressDenied,
    EgressPolicy,
    PinnedHttpsClient,
    ResponseTooLarge,
    UpstreamError,
    UpstreamTransient,
)

PROVIDER = "osm_overpass_schools"
RIGHTS_POLICY = "osm-odbl-2026-10"
PROVENANCE_HOST = "www.openstreetmap.org"
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)"
TERMS = "https://operations.osmfoundation.org/policies/api/ ; Overpass instance terms reviewed at activation"
LICENCE = "https://opendatacommons.org/licenses/odbl/1-0/ ; https://osmfoundation.org/wiki/Attribution_Guidelines"
QUERY_TIMEOUT_SECONDS = 20
USER_AGENT = "Hermecious-discovery/1.0 (self-hosted; bounded school POI query)"
_ELEMENT_TYPES = frozenset({"node", "way", "relation"})
_ALLOWED_TAGS = ("name", "name:ur", "addr:suburb")


class HttpClient(Protocol):
    requests: int

    def post_form(self, url: str, form: dict[str, str]) -> bytes: ...


def descriptor_from_settings(settings: Settings) -> SourceDescriptor:
    """Disabled (fail closed) unless every activation field has been set by the owner."""
    configured = bool(
        settings.osm_enabled
        and settings.osm_rights_reviewed_by
        and settings.osm_rights_reviewed_at
        and settings.osm_bbox
        and settings.osm_bbox_citation
    )
    return SourceDescriptor(
        provider=PROVIDER,
        adapter_version="1.0.0",
        source_kind="api",
        terms_reference=TERMS,
        rights_policy_version=RIGHTS_POLICY,
        permitted_operations=frozenset({Operation.SEARCH, Operation.FETCH, Operation.STORE_METADATA}),
        max_storage_class="metadata_only",
        retention_ttl=timedelta(days=30),
        request_quota=3,
        result_limit=30,
        page_size=30,
        allowed_hostnames=frozenset({PROVENANCE_HOST}),
        allow_http=False,
        requires_credentials=False,
        enabled=configured,
        environments=frozenset({"development", "test", "production"}),
        last_reviewed_at=settings.osm_rights_reviewed_at,
        reviewed_by=settings.osm_rights_reviewed_by,
        supported_cities=frozenset({"Lahore"}),
        supported_verticals=frozenset({"schools"}),
        licence_reference=LICENCE,
        attribution=ATTRIBUTION,
        max_response_bytes=1_000_000,
        retry_backoff_seconds=5.0,
        fetch_from_search_capture=True,
    )


def egress_policy(endpoint: str, descriptor: SourceDescriptor) -> EgressPolicy:
    from urllib.parse import urlsplit  # noqa: PLC0415

    parts = urlsplit(endpoint)
    return EgressPolicy(
        allowed=frozenset({((parts.hostname or "").lower(), parts.path)}),
        timeout_seconds=QUERY_TIMEOUT_SECONDS + 5,
        max_response_bytes=descriptor.max_response_bytes,
        user_agent=USER_AGENT,
    )


def adapter_from_settings(settings: Settings) -> "OsmOverpassAdapter":
    """The one place a live OSM adapter and its pinned egress client are built (CLI and worker)."""
    descriptor = descriptor_from_settings(settings)
    if not descriptor.enabled or not settings.osm_bbox:
        from app.discovery.registry import SourcePolicyError  # noqa: PLC0415

        raise SourcePolicyError("provider_disabled")
    http = PinnedHttpsClient(egress_policy(settings.osm_endpoint, descriptor))
    return OsmOverpassAdapter(descriptor, endpoint=settings.osm_endpoint, bbox=settings.osm_bbox, http=http)


def build_query(bbox: BBox, limit: int) -> str:
    """Fixed template; only validated numbers are interpolated."""
    if not 1 <= limit <= 31:
        raise ValueError("limit out of range")
    return f'[out:json][timeout:{QUERY_TIMEOUT_SECONDS}];nwr["amenity"="school"]({bbox.overpass()});out center {limit};'


_KEY = re.compile(r"(node|way|relation)/([1-9][0-9]{0,18})")


def provenance_url(source_key: str) -> str:
    match = _KEY.fullmatch(source_key)
    if match is None:
        raise ValueError("invalid OSM element key")
    return f"https://{PROVENANCE_HOST}/{match.group(1)}/{match.group(2)}"


class OsmOverpassAdapter:
    def __init__(
        self,
        descriptor: SourceDescriptor,
        *,
        endpoint: str,
        bbox: BBox | str,
        http: HttpClient,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._descriptor = descriptor
        self.endpoint = endpoint
        self.bbox = parse_bbox(bbox) if isinstance(bbox, str) else bbox
        self.http = http
        self.now = now
        self._observations: dict[str, dict[str, Any]] = {}

    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    def search(self, *, query: SourceQuery, limit: int, cursor: str | None = None) -> Mapping[str, Any]:
        if cursor is not None:  # single bounded query: Overpass has no cursor; never sweep for more
            return {"candidates": [], "next_cursor": None, "reported_cost_units": 0}
        try:
            body = self.http.post_form(self.endpoint, {"data": build_query(self.bbox, limit + 1)})
        except UpstreamTransient as exc:
            error = {"rate_limited": AdapterRateLimited, "timeout": AdapterTimeout}.get(exc.reason, AdapterUnavailable)
            raise error(exc.retry_after) from None
        except ResponseTooLarge:
            raise AdapterResponseTooLarge() from None
        except (UpstreamError, EgressDenied) as exc:
            raise AdapterUpstreamError(exc.reason) from None
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise AdapterUpstreamError("malformed_json") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
            raise AdapterUpstreamError("malformed_response")
        captured = self.now()
        base = _parse_time(
            payload.get("osm3s", {}).get("timestamp_osm_base") if isinstance(payload.get("osm3s"), dict) else None
        )
        elements = payload["elements"]
        candidates = [self._candidate(e, query, captured, base) for e in elements[:limit]]
        return {
            "candidates": candidates,
            "next_cursor": None,
            "reported_cost_units": 1,
            "truncated": len(elements) > limit,  # more matches exist than this bounded run may take
        }

    def _candidate(self, element: Any, query: SourceQuery, captured: datetime, base: datetime | None) -> dict[str, Any]:
        """Raw candidate; anything invalid is left for the framework's validation to reject."""
        if not isinstance(element, dict):
            return {"external_key": None}
        etype, eid = element.get("type"), element.get("id")
        valid_id = type(eid) is int and eid > 0
        key = f"{etype}/{eid}" if etype in _ELEMENT_TYPES and valid_id else None
        raw_tags = element.get("tags")
        tags: dict[str, Any] = raw_tags if isinstance(raw_tags, dict) else {}
        kept = {t: tags[t] for t in _ALLOWED_TAGS if isinstance(tags.get(t), str)}
        lat, lon, precision = None, None, None
        point = element if etype == "node" else element.get("center")
        if isinstance(point, dict) and _is_number(point.get("lat")) and _is_number(point.get("lon")):
            lat, lon = float(point["lat"]), float(point["lon"])
            precision = "point" if etype == "node" else "area_center"
            if not self.bbox.contains(lat, lon):
                key = None  # outside the configured area: never silently re-home it
        else:
            key = None  # unknown geometry: cannot show it is inside the configured area
        url = provenance_url(key) if key else None
        if key:
            self._observations[key] = {
                "provider": PROVIDER,
                "external_key": key,
                "observed_at": captured.isoformat(),
                "source_url": url,
                "permitted_storage_class": "metadata_only",
                "rights_policy_version": RIGHTS_POLICY,
                "expires_at": (captured + self._descriptor.retention_ttl).isoformat(),
                "data": {},
            }
        return {
            "provider": PROVIDER,
            "external_key": key,
            "display_name": kept.get("name"),
            "city": query.city,
            "vertical_slug": query.vertical_slug,
            "locality": kept.get("addr:suburb"),
            "source_url": url,
            "observed_at": captured.isoformat(),
            "claim_hints": [],
            "name_local": kept.get("name:ur"),
            "latitude": lat,
            "longitude": lon,
            "location_precision": precision,
            "upstream_timestamp": base.isoformat() if base else None,
            "attribution": ATTRIBUTION,
        }

    def fetch(self, *, source_key: str) -> Mapping[str, Any]:
        """Served from the observation captured in this run's search; no second request, no refresh faking."""
        observation = self._observations.get(source_key)
        if observation is None:
            raise KeyError(source_key)
        return observation


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
