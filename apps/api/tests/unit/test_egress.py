"""P2.2 LIVE-04/05/09 transport guard: the pinned HTTPS client, without any real network."""

import socket
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.core.settings import SettingsError, load_settings
from app.discovery import osm
from app.discovery.area import BBoxError, parse_bbox
from app.egress.https_client import (
    EgressDenied,
    EgressPolicy,
    PinnedHttpsClient,
    ResponseTooLarge,
    UpstreamError,
    UpstreamTransient,
)

ENDPOINT = "https://overpass-api.de/api/interpreter"
POLICY = EgressPolicy(
    allowed=frozenset({("overpass-api.de", "/api/interpreter")}),
    timeout_seconds=5,
    max_response_bytes=64,
    user_agent="test",
)


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    attempts: list[Any] = []

    def refuse(self: socket.socket, address: Any) -> None:
        attempts.append(address)
        raise OSError("egress blocked by test guard")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    yield attempts
    assert attempts == []


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"{}", headers: dict[str, str] | None = None) -> None:
        self.status, self.body, self.headers = status, body, headers or {}

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)

    def read(self, amt: int | None = None) -> bytes:
        return self.body[:amt] if amt is not None else self.body


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.sent: list[tuple[str, str, Any, Any]] = []
        self.closed = False

    def request(self, method: str, url: str, body: Any = None, headers: Any = None) -> None:
        self.sent.append((method, url, body, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def client(
    response: FakeResponse | None = None, addresses: list[str] | None = None
) -> tuple[PinnedHttpsClient, list[tuple[str, str, float]], list[FakeConnection]]:
    connects: list[tuple[str, str, float]] = []
    connections: list[FakeConnection] = []

    def connect(ip: str, host: str, timeout: float) -> FakeConnection:
        connects.append((ip, host, timeout))
        connection = FakeConnection(response or FakeResponse(200))
        connections.append(connection)
        return connection

    resolver: Callable[[str], list[str]] = lambda host: addresses or ["93.184.215.14"]  # noqa: E731
    return PinnedHttpsClient(POLICY, resolver=resolver, connect=connect), connects, connections


def test_success_pins_the_vetted_address_and_sends_a_fixed_form() -> None:
    http, connects, connections = client(FakeResponse(200, b'{"elements":[]}'))
    assert http.post_form(ENDPOINT, {"data": "q"}) == b'{"elements":[]}'
    assert connects == [("93.184.215.14", "overpass-api.de", 5)]
    method, path, body, headers = connections[0].sent[0]
    assert (method, path, body) == ("POST", "/api/interpreter", "data=q")
    assert headers["Host"] == "overpass-api.de" and "Cookie" not in headers and "Authorization" not in headers
    assert connections[0].closed and http.requests == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/other",
        "https://evil.example/api/interpreter",
        "https://overpass-api.de:8443/api/interpreter",
        "https://user:pw@overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter?data=x",
        "https://overpass-api.de/api/interpreter#frag",
        "https://169.254.169.254/api/interpreter",
    ],
)
def test_only_the_exact_allowlisted_target_is_reachable(url: str) -> None:
    http, connects, _ = client()
    with pytest.raises(EgressDenied) as error:
        http.post_form(url, {"data": "q"})
    assert error.value.reason == "target_not_allowed" and connects == [] and http.requests == 0


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["169.254.169.254"], ["10.0.0.7"], ["192.168.1.2"], ["::1"], ["fd00::1"], ["0.0.0.0"],  # noqa: S104
     ["93.184.215.14", "10.0.0.7"], ["100.64.0.1"], ["::ffff:127.0.0.1"]],
)  # fmt: skip
def test_dns_answers_with_any_non_public_address_are_refused_before_connecting(addresses: list[str]) -> None:
    http, connects, _ = client(addresses=addresses)
    with pytest.raises(EgressDenied) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert error.value.reason == "non_public_address" and connects == [] and http.requests == 0


def test_dns_failure_is_transient_and_makes_no_connection() -> None:
    def broken(host: str) -> list[str]:
        raise socket.gaierror("no such host")

    http = PinnedHttpsClient(POLICY, resolver=broken, connect=lambda *a: pytest.fail("connected"))
    with pytest.raises(UpstreamTransient) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert error.value.reason == "dns_failure"


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_refused_not_followed(status: int) -> None:
    http, connects, _ = client(FakeResponse(status, headers={"Location": "http://169.254.169.254/"}))
    with pytest.raises(EgressDenied) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert error.value.reason == "redirect_refused" and len(connects) == 1


@pytest.mark.parametrize(
    ("status", "header", "reason", "retry_after"),
    [
        (429, "7", "rate_limited", 7.0),
        (429, None, "rate_limited", None),
        (503, "12", "unavailable", 12.0),
        (429, "Wed, 21 Oct 2026 07:28:00 GMT", "rate_limited", None),
        (429, "100000", "rate_limited", None),
        (429, "-3", "rate_limited", None),
    ],
)
def test_rate_limits_become_typed_transients_with_bounded_retry_after(
    status: int, header: str | None, reason: str, retry_after: float | None
) -> None:
    http, _, _ = client(FakeResponse(status, headers={"Retry-After": header} if header else {}))
    with pytest.raises(UpstreamTransient) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert (error.value.reason, error.value.retry_after) == (reason, retry_after)


def test_other_errors_and_oversized_bodies_are_permanent() -> None:
    http, _, _ = client(FakeResponse(400))
    with pytest.raises(UpstreamError) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert error.value.reason == "http_400"
    http, _, connections = client(FakeResponse(200, b"x" * 65))
    with pytest.raises(ResponseTooLarge):
        http.post_form(ENDPOINT, {"data": "q"})
    assert connections[0].closed


def test_timeouts_are_transient() -> None:
    def slow(ip: str, host: str, timeout: float) -> FakeConnection:
        raise TimeoutError

    http = PinnedHttpsClient(POLICY, resolver=lambda host: ["93.184.215.14"], connect=slow)
    with pytest.raises(UpstreamTransient) as error:
        http.post_form(ENDPOINT, {"data": "q"})
    assert error.value.reason == "timeout"


def test_proxy_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.9:3128")
    monkeypatch.setenv("ALL_PROXY", "http://10.0.0.9:3128")
    http, connects, _ = client()
    http.post_form(ENDPOINT, {"data": "q"})
    assert connects[0][0] == "93.184.215.14"


# --- area and query builder (LIVE-03/04) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["", "31,74,32", "a,b,c,d", "nan,74,31.6,74.5", "31.6,74,31.4,74.5", "30.0,73.0,32.0,75.0",
     "-31.6,74.1,-31.4,74.5", "51.4,-0.2,51.6,0.1", "31.4,74.1,31.6,inf"],
)  # fmt: skip
def test_bbox_must_be_explicit_finite_small_and_plausible(raw: str) -> None:
    with pytest.raises(BBoxError):
        parse_bbox(raw)


def test_query_is_a_fixed_template_with_only_validated_numbers() -> None:
    bbox = parse_bbox("31.30,74.10,31.70,74.55")
    assert osm.build_query(bbox, 31) == (
        '[out:json][timeout:20];nwr["amenity"="school"](31.300000,74.100000,31.700000,74.550000);out center 31;'
    )
    for limit in (0, 32, 1000):
        with pytest.raises(ValueError, match="limit"):
            osm.build_query(bbox, limit)


@pytest.mark.parametrize("key", ["node/0", "way/-1", "area/5", "node/1/../../x", "node/abc", "https://x/node/1"])
def test_provenance_urls_come_only_from_validated_element_keys(key: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        osm.provenance_url(key)
    assert osm.provenance_url("relation/42") == "https://www.openstreetmap.org/relation/42"


# --- activation settings (LIVE-01) --------------------------------------------------------------------------

BASE = {
    "DATABASE_URL": "postgresql://u:p@postgres:5432/db",
    "REDIS_URL": "redis://redis:6379/0",
    "HERMECIOUS_ENV": "development",
    "HERMECIOUS_ALLOWED_ORIGINS": "http://localhost:3000",
}
ACTIVE = {
    "HERMECIOUS_OSM_ENABLED": "true",
    "HERMECIOUS_OSM_REVIEWED_BY": "owner@example.invalid",
    "HERMECIOUS_OSM_REVIEWED_AT": "2026-10-23T00:00:00+00:00",
    "HERMECIOUS_OSM_BBOX": "31.30,74.10,31.70,74.55",
    "HERMECIOUS_OSM_BBOX_CITATION": "operator-chosen test box",
}


@pytest.fixture
def set_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    for name in [*BASE, *ACTIVE, "HERMECIOUS_OSM_ENDPOINT"]:
        monkeypatch.delenv(name, raising=False)

    def apply(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return apply


def test_osm_is_disabled_by_default_and_the_descriptor_fails_closed(set_env: Callable[..., None]) -> None:
    set_env(**BASE)
    settings = load_settings()
    assert settings.osm_enabled is False
    descriptor = osm.descriptor_from_settings(settings)
    assert descriptor.enabled is False and descriptor.reviewed_by is None


@pytest.mark.parametrize(
    ("override", "named"),
    [
        ({"HERMECIOUS_OSM_REVIEWED_BY": ""}, "HERMECIOUS_OSM_REVIEWED_BY"),
        ({"HERMECIOUS_OSM_REVIEWED_AT": "2026-10-23T00:00:00"}, "HERMECIOUS_OSM_REVIEWED_AT"),
        ({"HERMECIOUS_OSM_BBOX": "30.0,73.0,32.0,75.0"}, "HERMECIOUS_OSM_BBOX"),
        ({"HERMECIOUS_OSM_BBOX_CITATION": ""}, "HERMECIOUS_OSM_BBOX_CITATION"),
        ({"HERMECIOUS_OSM_ENDPOINT": "https://evil.example/api/interpreter"}, "HERMECIOUS_OSM_ENDPOINT"),
        ({"HERMECIOUS_OSM_ENDPOINT": "http://overpass-api.de/api/interpreter"}, "HERMECIOUS_OSM_ENDPOINT"),
    ],
)
def test_enabling_osm_requires_every_reviewed_activation_setting(
    set_env: Callable[..., None], override: dict[str, str], named: str
) -> None:
    set_env(**BASE, **{**ACTIVE, **override})
    with pytest.raises(SettingsError) as error:
        load_settings()
    assert named in str(error.value)
    assert "evil.example" not in str(error.value)


def test_fully_reviewed_activation_enables_the_descriptor(set_env: Callable[..., None]) -> None:
    set_env(**BASE, **ACTIVE)
    descriptor = osm.descriptor_from_settings(load_settings())
    assert descriptor.enabled and descriptor.reviewed_by == "owner@example.invalid"
    assert descriptor.max_storage_class == "metadata_only" and descriptor.request_quota == 3
    assert "OpenStreetMap contributors" in str(descriptor.attribution)
