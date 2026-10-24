"""Allowlisted source descriptors and fail-closed policy checks (P2.1).

P2.1 ships exactly one synthetic fixture provider. Real providers arrive in
P2.2 only after an explicit rights review recorded in their descriptor.
"""

from datetime import UTC, datetime, timedelta

from app.discovery.contracts import Operation, SourceDescriptor

FIXTURE_PROVIDER = "fixture_lahore_schools"
FIXTURE_RIGHTS_POLICY = "fixture-synthetic-2026-10"

DESCRIPTORS: dict[str, SourceDescriptor] = {
    FIXTURE_PROVIDER: SourceDescriptor(
        provider=FIXTURE_PROVIDER,
        adapter_version="1.0.0",
        source_kind="fixture",
        # Internally authored synthetic data; this policy id applies to the fixture only, never to real providers.
        terms_reference="fixture-policy:hermecious-synthetic-v1",
        rights_policy_version=FIXTURE_RIGHTS_POLICY,
        permitted_operations=frozenset(Operation),
        max_storage_class="full_allowed",
        retention_ttl=timedelta(days=30),
        request_quota=20,
        result_limit=30,
        page_size=3,
        allowed_hostnames=frozenset({"school.fixture.example"}),
        allow_http=False,
        requires_credentials=False,
        enabled=True,
        environments=frozenset({"development", "test"}),
        last_reviewed_at=datetime(2026, 10, 24, tzinfo=UTC),
        supported_cities=frozenset({"Lahore"}),
        supported_verticals=frozenset({"schools"}),
    )
}

_CLASS_RANK = {"metadata_only": 0, "derived_only": 1, "full_allowed": 2}


class SourcePolicyError(ValueError):
    """Refused by source policy before the adapter is invoked. `reason` is a fixed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve(provider: str, environment: str) -> SourceDescriptor:
    descriptor = DESCRIPTORS.get(provider)
    if descriptor is None:
        raise SourcePolicyError("unknown_provider")
    check_descriptor(descriptor, environment)
    return descriptor


def check_descriptor(descriptor: SourceDescriptor, environment: str) -> None:
    """Fail closed unless the descriptor is enabled, reviewed and allowed here."""
    if not descriptor.enabled:
        raise SourcePolicyError("provider_disabled")
    if not descriptor.terms_reference or not descriptor.rights_policy_version or descriptor.last_reviewed_at is None:
        raise SourcePolicyError("provider_unreviewed")
    if descriptor.source_kind != "fixture":
        raise SourcePolicyError("live_sources_not_enabled")  # P2.1 is offline-only
    if environment not in descriptor.environments:
        raise SourcePolicyError("provider_not_enabled_in_environment")
    if descriptor.requires_credentials:
        raise SourcePolicyError("credentials_not_supported")


def require_operation(descriptor: SourceDescriptor, operation: Operation) -> None:
    if operation not in descriptor.permitted_operations:
        raise SourcePolicyError(f"operation_not_licensed:{operation.value}")


def storage_allowed(descriptor: SourceDescriptor, storage_class: str) -> bool:
    return _CLASS_RANK[storage_class] <= _CLASS_RANK[descriptor.max_storage_class]
