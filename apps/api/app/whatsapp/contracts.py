"""Versioned provider contracts (P5.1, ADR-026). Strict: unknown fields, bad lengths and naive times are refused.

These are transport facts, never authorizations: an accepted send is not delivery, and an inbound message is
never marketing consent.
"""

import re
import uuid
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "whatsapp-contracts-1.0"
WAMID = re.compile(r"wamid\.[A-Za-z0-9+/=_-]{8,240}")
MAX_COMPONENTS = 5
MAX_PARAMETERS = 10
MAX_PARAMETER_CHARS = 200
# A template parameter is plain text: never a link, a phone number or an instruction to the transport.
_UNSAFE_PARAMETER = re.compile(r"(?i)https?://|www\.|\+?\d[\d\s-]{6,}\d|[\u0000-\u001f\u007f‪-‮⁦-⁩]")


class ProviderEnvironment(StrEnum):
    SIMULATION = "simulation"
    CONTRACT_TEST = "contract_test"
    PROVIDER_TEST = "provider_test"
    PRODUCTION = "production"


class OutboundKind(StrEnum):
    TEMPLATE = "template"
    SERVICE_TEXT = "service_text"  # typed for completeness; NOT send-capable in Batch 08


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemplateParameter(_Strict):
    type: Literal["text"] = "text"
    text: Annotated[str, Field(min_length=1, max_length=MAX_PARAMETER_CHARS)]

    @field_validator("text")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        if _UNSAFE_PARAMETER.search(value):
            raise ValueError("template parameters must be plain text (no links, numbers or control characters)")
        return value


class TemplateComponent(_Strict):
    type: Literal["header", "body"]
    parameters: Annotated[list[TemplateParameter], Field(max_length=MAX_PARAMETERS)]


class SendIntent(_Strict):
    operation_id: uuid.UUID
    organization_id: uuid.UUID
    provider_connection_id: uuid.UUID
    purpose: Literal["marketing", "utility", "service_reply", "operator_test"]
    recipient_ref: uuid.UUID  # an internal registry reference; there is no phone or URL field at all
    kind: OutboundKind
    template_name: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,512}$")] | None
    template_language: Annotated[str, Field(pattern=r"^[a-z]{2,3}(_[A-Z]{2})?$")] | None
    template_components: Annotated[list[TemplateComponent], Field(max_length=MAX_COMPONENTS)] | None = None
    draft_revision_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None
    approval_id: uuid.UUID | None
    policy_revision: Annotated[str, Field(min_length=1, max_length=60)]
    created_at_utc: AwareDatetime
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class SendResult(_Strict):
    operation_id: uuid.UUID
    outcome: Literal["accepted", "definitive_rejected", "indeterminate"]
    provider_message_id: str | None
    provider_message_status: Literal["accepted", "held_for_quality_assessment", "paused"] | None = None
    provider_error_code: str | None
    error_class: str | None = None
    retriable: bool
    received_at_utc: AwareDatetime


class DeliveryUpdate(_Strict):
    provider_message_id: str
    phone_number_id: str
    status: Literal["sent", "delivered", "read", "failed", "unknown"]
    provider_timestamp_utc: AwareDatetime
    error_code: str | None = None
    dedupe_key: str


class IncomingMessage(_Strict):
    provider_message_id: str
    phone_number_id: str
    sender_identity_ref: str  # keyed digest (P4.3); never the raw number
    provider_timestamp_utc: AwareDatetime
    kind: Literal["text", "image", "document", "interactive", "unsupported"]
    safe_content_ref: str | None
    dedupe_key: str


class TemplateDescriptor(_Strict):
    waba_id: str
    template_id: str
    name: str
    language: str
    category: str  # the provider's own string (MARKETING, UTILITY, AUTHENTICATION, ...)
    provider_status: str  # APPROVED, PENDING, REJECTED, PAUSED, ... exactly as returned
    components_digest: str
    body_parameter_count: int
    header_parameter_count: int
    body_text: str | None = None  # the approved body, for an exact operator preview
    supported: bool = True  # False when components need parameters we cannot type safely (media, URL buttons)
    fetched_at_utc: AwareDatetime
    source: Literal["meta", "contract_fixture"] = "meta"


class ProviderConnectionView(_Strict):
    connection_id: uuid.UUID
    organization_id: uuid.UUID
    waba_id: Annotated[str, Field(pattern=r"^[0-9]{5,20}$")]  # digits only: these become URL path segments
    phone_number_id: Annotated[str, Field(pattern=r"^[0-9]{5,20}$")]
    graph_version: Annotated[str, Field(pattern=r"^v[0-9]{2}\.0$")]
    mode: ProviderEnvironment
    enabled: bool
    credential_ref: str  # the *name* of the secret source, never the secret


class ResolvedRecipient(_Strict):
    """Produced only by a server-side registry lookup (P5.3); the transport never reads a number from a request."""

    recipient_ref: uuid.UUID
    e164: Annotated[str, Field(pattern=r"^\+[1-9][0-9]{7,14}$")]


ErrorClass = Literal[
    "validation", "authn", "authz", "policy_denied", "provider_bad_request", "provider_auth", "provider_quota",
    "provider_transient", "provider_uncertain", "webhook_signature", "webhook_unmapped", "payload_invalid",
    "storage_unavailable", "concurrency_conflict", "unknown",
]  # fmt: skip
