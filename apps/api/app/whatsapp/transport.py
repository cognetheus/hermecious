"""Meta WhatsApp Cloud API transport (P5.1, ADR-026). Template messages only; one fixed official host.

Nothing in the application dispatches through this module in P5.1: no route, job or campaign path reaches
`send_template`. P5.3 adds the single guarded operator test path.

**Outcome semantics:**
- `accepted`: Graph returned a `wamid` for the call. This is not `sent`, `delivered` or `read`; those come only
  from signed webhooks (P5.2).
- `definitive_rejected`: Graph answered with an error, or the connection failed before any request bytes were
  written. Carries a typed, non-sensitive error class and a retry class.
- `indeterminate`: the request may have reached Meta (timeout or reset after the write, a malformed or oversized
  2xx). Never resent automatically; a person reconciles.

Graph does not offer an idempotency key for `/messages`: application idempotency is an internal guarantee only.
"""

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from app.core.settings import Settings
from app.egress.https_client import (
    EgressDenied,
    EgressPolicy,
    PinnedHttpsClient,
    ResponseTooLarge,
    UpstreamTransient,
    UpstreamUncertain,
)
from app.simulations.transport import LiveTransportForbidden
from app.whatsapp.config import GRAPH_HOST, SUPPORTED_GRAPH_VERSIONS
from app.whatsapp.contracts import (
    WAMID,
    OutboundKind,
    ProviderConnectionView,
    ResolvedRecipient,
    SendIntent,
    SendResult,
    TemplateDescriptor,
)

logger = logging.getLogger("app.whatsapp")
TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 64 * 1024
USER_AGENT = "Hermecious/1.0 (+whatsapp-cloud-api; operator-confirmed only)"
# Provider category per purpose; anything else (including AUTHENTICATION or an unknown string) fails closed.
CATEGORIES = {
    "marketing": frozenset({"MARKETING"}),
    "utility": frozenset({"UTILITY"}),
    "operator_test": frozenset({"MARKETING", "UTILITY"}),
}
_QUOTA_CODES = frozenset({4, 17, 32, 613, 80007, 130429, 131048, 131056})
_AUTH_CODES = frozenset({10, 190, 200})


class ProviderCallError(Exception):
    """Refused before any network call (policy, binding, template or payload). `error_class` is log-safe."""

    def __init__(self, error_class: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.error_class = error_class
        self.safe_message = safe_message


class GraphHttp(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        bearer: str | None = None,
    ) -> tuple[int, bytes]: ...


def components_digest(components: Any) -> str:
    return hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _error(
    operation_id: uuid.UUID, now: datetime, error_class: str, code: str | None, retriable: bool, outcome: str
) -> SendResult:
    return SendResult(
        operation_id=operation_id,
        outcome=outcome,  # type: ignore[arg-type]
        provider_message_id=None,
        provider_error_code=code,
        error_class=error_class,
        retriable=retriable,
        received_at_utc=now,
    )


def parse_send_response(operation_id: uuid.UUID, status: int, raw: bytes, now: datetime) -> SendResult:
    """Typed result from a Graph `/messages` response. Never invents a provider id."""
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if 200 <= status < 300:
        messages = data.get("messages") if isinstance(data, dict) else None
        if (
            isinstance(data, dict)
            and data.get("messaging_product") == "whatsapp"
            and isinstance(messages, list)
            and len(messages) == 1
            and isinstance(messages[0], dict)
            and isinstance(messages[0].get("id"), str)
            and WAMID.fullmatch(messages[0]["id"])
            and messages[0].get("message_status", "accepted") in ("accepted", "held_for_quality_assessment", "paused")
        ):
            return SendResult(
                operation_id=operation_id,
                outcome="accepted",
                provider_message_id=messages[0]["id"],
                provider_message_status=messages[0].get("message_status", "accepted"),
                provider_error_code=None,
                retriable=False,
                received_at_utc=now,
            )
        # A 2xx we cannot read may still have sent a message: unknown, not a failure and not a success.
        return _error(operation_id, now, "provider_uncertain", None, False, "indeterminate")
    error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), int) else None
    safe_code = str(code) if code is not None else None
    if status == 401 or code in _AUTH_CODES or status == 403:
        return _error(operation_id, now, "provider_auth", safe_code, False, "definitive_rejected")
    if status == 429 or code in _QUOTA_CODES:
        return _error(operation_id, now, "provider_quota", safe_code, True, "definitive_rejected")
    if status >= 500:
        return _error(operation_id, now, "provider_transient", safe_code, True, "definitive_rejected")
    return _error(operation_id, now, "provider_bad_request", safe_code, False, "definitive_rejected")


_PLACEHOLDER = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_CURSOR = re.compile(r"[A-Za-z0-9=_-]{1,200}")
TEMPLATE_FIELDS = "id,name,language,category,status,components"
MAX_TEMPLATE_PAGES = 10


def _placeholders(text: Any) -> int:
    return len(set(_PLACEHOLDER.findall(text))) if isinstance(text, str) else 0


def parse_templates(raw: bytes, waba_id: str, now: datetime) -> tuple[list[TemplateDescriptor], str | None]:
    """One page of `GET /{waba}/message_templates`. Provider strings are kept exactly; bad entries are skipped."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderCallError("provider_uncertain", "the template list could not be read") from None
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderCallError("provider_uncertain", "the template list could not be read")
    out: list[TemplateDescriptor] = []
    for row in rows[:200]:
        if not isinstance(row, dict):
            continue
        fields = (row.get("id"), row.get("name"), row.get("language"), row.get("category"), row.get("status"))
        if not all(isinstance(f, str) and 0 < len(f) <= 512 for f in fields):
            continue
        raw_components = row.get("components")
        components: list[Any] = raw_components if isinstance(raw_components, list) else []
        body = next((c for c in components if isinstance(c, dict) and c.get("type") == "BODY"), None)
        header = next((c for c in components if isinstance(c, dict) and c.get("type") == "HEADER"), None)
        supported = all(isinstance(c, dict) for c in components)
        if header is not None and header.get("format", "TEXT") != "TEXT":
            supported = False  # media headers need a media parameter we do not send
        for c in components:
            if isinstance(c, dict) and c.get("type") == "BUTTONS" and "{{" in json.dumps(c.get("buttons", [])):
                supported = False  # URL-variable buttons
        try:
            out.append(
                TemplateDescriptor(
                    waba_id=waba_id, template_id=str(row["id"]), name=str(row["name"]), language=str(row["language"]),
                    category=str(row["category"]), provider_status=str(row["status"]),
                    components_digest=components_digest(components),
                    body_parameter_count=_placeholders(body.get("text") if body else None),
                    header_parameter_count=_placeholders(header.get("text") if header else None),
                    body_text=str(body.get("text"))[:1024] if body and isinstance(body.get("text"), str) else None,
                    supported=supported, fetched_at_utc=now,
                )
            )  # fmt: skip
        except ValueError:
            continue
    raw_paging = data.get("paging")
    paging: dict[str, Any] = raw_paging if isinstance(raw_paging, dict) else {}
    raw_cursors = paging.get("cursors")
    cursors: dict[str, Any] = raw_cursors if isinstance(raw_cursors, dict) else {}
    after = cursors.get("after")
    cursor = after if paging.get("next") and isinstance(after, str) and _CURSOR.fullmatch(after) else None
    return out, cursor


class MetaCloudTransport:
    """One connection, one official host, template sends only. Construct only through `build_transport`."""

    def __init__(
        self,
        connection: ProviderConnectionView,
        http: GraphHttp,
        token: Callable[[], str],
        now: Callable[[], datetime],
    ) -> None:
        if connection.graph_version not in SUPPORTED_GRAPH_VERSIONS:
            raise ProviderCallError("validation", "unsupported Graph API version")
        self.connection = connection
        self._http = http
        self._token = token
        self._now = now

    @property
    def messages_url(self) -> str:
        return f"https://{GRAPH_HOST}/{self.connection.graph_version}/{self.connection.phone_number_id}/messages"

    @property
    def templates_url(self) -> str:
        return f"https://{GRAPH_HOST}/{self.connection.graph_version}/{self.connection.waba_id}/message_templates"

    def build_payload(
        self, intent: SendIntent, recipient: ResolvedRecipient, template: TemplateDescriptor
    ) -> dict[str, Any]:
        """Every check that can refuse without the network. Raises `ProviderCallError`."""
        c = self.connection
        if intent.kind != OutboundKind.TEMPLATE:
            raise ProviderCallError("policy_denied", "only approved template messages can be sent")
        if (intent.organization_id, intent.provider_connection_id) != (c.organization_id, c.connection_id):
            raise ProviderCallError("authz", "the intent belongs to another organization or connection")
        if not c.enabled:
            raise ProviderCallError("policy_denied", "the provider connection is disabled")
        if recipient.recipient_ref != intent.recipient_ref:
            raise ProviderCallError("validation", "the resolved recipient does not match the intent")
        if template.waba_id != c.waba_id:
            raise ProviderCallError("authz", "the template belongs to another WhatsApp Business Account")
        if (template.name, template.language) != (intent.template_name, intent.template_language):
            raise ProviderCallError("validation", "the template does not match the intent")
        if not template.supported:
            raise ProviderCallError("policy_denied", "the template has components this sender cannot fill safely")
        if template.provider_status != "APPROVED":
            raise ProviderCallError("policy_denied", "the template is not currently APPROVED by Meta")
        if template.category not in CATEGORIES.get(intent.purpose, frozenset()):
            raise ProviderCallError("policy_denied", "the template category does not fit this purpose")
        components = intent.template_components or []
        counts = {"header": 0, "body": 0}
        for component in components:
            counts[component.type] += len(component.parameters)
        if (counts["header"], counts["body"]) != (template.header_parameter_count, template.body_parameter_count):
            raise ProviderCallError("validation", "parameters do not match the approved template's placeholders")
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient.e164.removeprefix("+"),
            "type": "template",
            "template": {
                "name": template.name,
                "language": {"code": template.language},
                "components": [c.model_dump() for c in components if c.parameters],
            },
        }

    def send_template(
        self, intent: SendIntent, recipient: ResolvedRecipient, template: TemplateDescriptor
    ) -> SendResult:
        payload = self.build_payload(intent, recipient, template)
        now = self._now()
        try:
            status, raw = self._http.request_json("POST", self.messages_url, body=payload, bearer=self._token())
        except UpstreamUncertain:
            result = _error(intent.operation_id, now, "provider_uncertain", None, False, "indeterminate")
        except ResponseTooLarge:
            result = _error(intent.operation_id, now, "provider_uncertain", None, False, "indeterminate")
        except UpstreamTransient:  # failed before any request bytes were written: nothing was sent
            result = _error(intent.operation_id, now, "provider_transient", None, True, "definitive_rejected")
        except EgressDenied:
            result = _error(intent.operation_id, now, "policy_denied", None, False, "definitive_rejected")
        else:
            result = parse_send_response(intent.operation_id, status, raw, now)
        logger.info(
            "whatsapp.send_result",
            extra={"context": {"operation_id": str(intent.operation_id), "outcome": result.outcome,
                               "error_class": result.error_class, "provider_error_code": result.provider_error_code}},
        )  # fmt: skip
        return result

    def list_templates(self, name: str | None = None) -> list[TemplateDescriptor]:
        """Read-only, paginated (bounded) template catalog for this connection's WABA. Raises `ProviderCallError`."""
        found: list[TemplateDescriptor] = []
        after: str | None = None
        for _page in range(MAX_TEMPLATE_PAGES):
            query = {"fields": TEMPLATE_FIELDS, "limit": "50"}
            if name is not None:
                query["name"] = name
            if after is not None:
                query["after"] = after
            try:
                status, raw = self._http.request_json("GET", self.templates_url, query=query, bearer=self._token())
            except (UpstreamUncertain, UpstreamTransient, ResponseTooLarge):
                raise ProviderCallError("provider_transient", "the template catalog could not be fetched") from None
            except EgressDenied:
                raise ProviderCallError("policy_denied", "the template catalog endpoint is not allowed") from None
            if status != 200:
                mapped = parse_send_response(uuid.uuid4(), status, raw, self._now())
                raise ProviderCallError(mapped.error_class or "unknown", "the provider refused the template request")
            page, after = parse_templates(raw, self.connection.waba_id, self._now())
            found.extend(page)
            if after is None:
                break
        return found

    def health_check(self) -> dict[str, Any]:
        """Read-only and credential-safe: can the token read this phone-number resource? Returns no identifiers."""
        url = f"https://{GRAPH_HOST}/{self.connection.graph_version}/{self.connection.phone_number_id}"
        try:
            status, _raw = self._http.request_json("GET", url, query={"fields": "id"}, bearer=self._token())
        except (UpstreamUncertain, UpstreamTransient, ResponseTooLarge, EgressDenied) as exc:
            return {"ok": False, "error_class": "provider_transient", "reason": exc.reason}
        if status == 200:
            return {"ok": True, "error_class": None}
        mapped = parse_send_response(uuid.uuid4(), status, _raw, self._now())
        return {"ok": False, "error_class": mapped.error_class, "provider_error_code": mapped.provider_error_code}


def egress_policy(connection: ProviderConnectionView) -> EgressPolicy:
    """Exactly the three Graph paths this connection may use; nothing else is reachable."""
    v, phone, waba = connection.graph_version, connection.phone_number_id, connection.waba_id
    return EgressPolicy(
        allowed=frozenset(
            {
                (GRAPH_HOST, f"/{v}/{phone}/messages"),
                (GRAPH_HOST, f"/{v}/{waba}/message_templates"),
                (GRAPH_HOST, f"/{v}/{phone}"),
            }
        ),  # fmt: skip
        timeout_seconds=TIMEOUT_SECONDS,
        max_response_bytes=MAX_RESPONSE_BYTES,
        user_agent=USER_AGENT,
    )


def build_transport(
    settings: Settings,
    connection: ProviderConnectionView,
    now: Callable[[], datetime],
    http: GraphHttp | None = None,
) -> MetaCloudTransport:
    """The only constructor. It can never raise a mode's capability:
    - simulation: no provider client at all (the P4.5 fake is the only transport);
    - production: no outbound transport until the P5.5 go/no-go;
    - contract_test: an injected local fake only, in the test environment;
    - provider_test: the pinned Graph client, bound to the configured *test* WABA/phone.
    """
    mode = settings.whatsapp_mode
    if mode == "simulation" or settings.live_outbound_enabled:
        raise LiveTransportForbidden("simulation mode has no provider client")
    if mode == "production":
        raise LiveTransportForbidden("production outbound is disabled until the P5.5 go/no-go")
    if connection.mode != mode:
        raise ProviderCallError("authz", "the connection was bound for another mode")
    if mode == "contract_test":
        if settings.environment != "test" or http is None:
            raise LiveTransportForbidden("contract tests use an injected local fake only")
        return MetaCloudTransport(connection, http, lambda: "contract-test-token", now)
    # provider_test: credentials and IDs come from settings and must equal the bound connection exactly.
    if (connection.waba_id, connection.phone_number_id) != (
        settings.whatsapp_waba_id,
        settings.whatsapp_phone_number_id,
    ):
        raise ProviderCallError("authz", "the connection does not match the configured credentials")
    if connection.graph_version != settings.whatsapp_graph_version:
        raise ProviderCallError("validation", "the connection's Graph version does not match the configuration")
    token = settings.whatsapp_access_token
    if token is None:  # pragma: no cover  # settings validation requires it in provider_test
        raise LiveTransportForbidden("no access token configured")
    client = http if http is not None else PinnedHttpsClient(egress_policy(connection))
    return MetaCloudTransport(connection, client, token.get_secret_value, now)
