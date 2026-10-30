"""The only outbound HTTP client in Hermecious (P2.2, ADR-013). Deliberately small.

Rules: HTTPS to an exact (host, path) allowlist on port 443; DNS resolved once
and EVERY address must be globally routable, then the TCP connection is pinned
to a vetted address while TLS still verifies the hostname (DNS-rebinding
safe); no redirects, no proxies, no credentials, no cookies; bounded time and
bounded response bytes; 429/503 become typed transient errors with Retry-After.
"""

import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

MAX_RETRY_AFTER_SECONDS = 300


class EgressError(Exception):
    """Base class; `reason` is a fixed, log-safe code."""

    reason = "egress_error"

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(reason or self.reason)
        if reason:
            self.reason = reason


class EgressDenied(EgressError):
    reason = "egress_denied"


class UpstreamTransient(EgressError):
    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.retry_after = retry_after


class UpstreamError(EgressError):
    reason = "upstream_error"


class ResponseTooLarge(EgressError):
    reason = "response_too_large"


class UpstreamUncertain(EgressError):
    """The request bytes may have reached the provider before the failure: the outcome is unknown.

    Callers of non-idempotent operations (a message send) must record `indeterminate` and never resend blindly.
    """

    reason = "outcome_unknown"


@dataclass(frozen=True)
class EgressPolicy:
    allowed: frozenset[tuple[str, str]]  # exact (hostname, path) pairs
    timeout_seconds: float
    max_response_bytes: int
    user_agent: str


class _Response(Protocol):
    status: int

    def getheader(self, name: str) -> str | None: ...

    def read(self, amt: int | None = None) -> bytes: ...


class _Connection(Protocol):
    def request(self, method: str, url: str, body: Any = None, headers: Any = ...) -> None: ...

    def getresponse(self) -> _Response: ...

    def close(self) -> None: ...


Resolver = Callable[[str], list[str]]
Connector = Callable[[str, str, float], _Connection]


def system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def pinned_tls_connector(ip: str, host: str, timeout: float) -> _Connection:
    """TCP to the vetted IP; TLS with SNI + certificate verification for `host`."""
    context = ssl.create_default_context()
    raw = socket.create_connection((ip, 443), timeout=timeout)
    tls = context.wrap_socket(raw, server_hostname=host)
    connection = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
    connection.sock = tls  # already connected and verified; http.client will not reconnect elsewhere
    return connection


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None  # HTTP-date form is not trusted; treat as unknown
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER_SECONDS else None


class PinnedHttpsClient:
    def __init__(
        self, policy: EgressPolicy, resolver: Resolver = system_resolver, connect: Connector = pinned_tls_connector
    ) -> None:
        self.policy = policy
        self.resolver = resolver
        self.connect = connect
        self.requests = 0  # observable request count for budgets and evidence

    def _check_target(self, url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
            raise EgressDenied("target_not_allowed")
        if parts.port not in (None, 443):
            raise EgressDenied("target_not_allowed")
        host = (parts.hostname or "").lower()
        if (host, parts.path) not in self.policy.allowed:
            raise EgressDenied("target_not_allowed")
        return host, parts.path

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        bearer: str | None = None,
    ) -> tuple[int, bytes]:
        """JSON over the same pinned, allowlisted transport (P5.1, ADR-026). Returns (status, bounded body).

        Unlike `post_form`, a non-2xx status is returned for the caller's typed mapping. The bearer credential is
        a header only; it is never part of the URL, a log line or an exception message.
        """
        if method not in ("GET", "POST"):
            raise EgressDenied("method_not_allowed")
        host, path = self._check_target(url)
        try:
            addresses = self.resolver(host)
        except OSError:
            raise UpstreamTransient("dns_failure") from None
        if not addresses or not all(_is_public(a) for a in addresses):
            raise EgressDenied("non_public_address")
        self.requests += 1
        try:
            connection = self.connect(addresses[0], host, self.policy.timeout_seconds)
        except TimeoutError:
            raise UpstreamTransient("connect_timeout") from None  # nothing was sent
        except (OSError, ssl.SSLError):
            raise UpstreamTransient("connect_failed") from None
        headers = {"Host": host, "User-Agent": self.policy.user_agent, "Accept": "application/json"}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        payload = None
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        target = path + ("?" + urlencode(query) if query else "")
        try:
            connection.request(method, target, body=payload, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise EgressDenied("redirect_refused")
            data = response.read(self.policy.max_response_bytes + 1)
            if len(data) > self.policy.max_response_bytes:
                raise ResponseTooLarge()
            return response.status, data
        except (OSError, ssl.SSLError, http.client.HTTPException):  # includes timeouts after the write began
            raise UpstreamUncertain() from None
        finally:
            connection.close()

    def post_form(self, url: str, form: dict[str, str]) -> bytes:
        host, path = self._check_target(url)
        try:
            addresses = self.resolver(host)
        except OSError:
            raise UpstreamTransient("dns_failure") from None
        if not addresses or not all(_is_public(a) for a in addresses):
            raise EgressDenied("non_public_address")  # any private/loopback/metadata answer poisons the lookup
        self.requests += 1
        try:
            connection = self.connect(addresses[0], host, self.policy.timeout_seconds)
        except TimeoutError:
            raise UpstreamTransient("timeout") from None
        except (OSError, ssl.SSLError):
            raise UpstreamTransient("connect_failed") from None
        try:
            connection.request(
                "POST",
                path,
                body=urlencode(form),
                headers={
                    "Host": host,
                    "User-Agent": self.policy.user_agent,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise EgressDenied("redirect_refused")
            if response.status in (429, 503):
                raise UpstreamTransient(
                    "rate_limited" if response.status == 429 else "unavailable",
                    _retry_after(response.getheader("Retry-After")),
                )
            if response.status != 200:
                raise UpstreamError(f"http_{response.status}")
            body = response.read(self.policy.max_response_bytes + 1)
            if len(body) > self.policy.max_response_bytes:
                raise ResponseTooLarge()
            return body
        except TimeoutError:
            raise UpstreamTransient("timeout") from None
        except (OSError, ssl.SSLError, http.client.HTTPException):  # reset, TLS failure, truncated response
            raise UpstreamTransient("connection_failed") from None
        finally:
            connection.close()
