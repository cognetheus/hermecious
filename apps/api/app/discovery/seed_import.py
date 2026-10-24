"""Operator-supplied CSV seed import (P2.2 fallback source, ADR-013).

The operator declares where the list came from and that they may use it; the
rows are user-seeded and NOT independently verified. Nothing is fetched (a
`source_reference` that looks like a URL is kept as text), no contacts are
extracted, and formula-like cells are refused so nothing becomes a spreadsheet
instruction on a later export. Idempotent per (organization, provider, file
checksum): re-importing the same bytes changes nothing.
"""

import csv
import hashlib
import io
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management, policy
from app.accounts import service as source_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import InvalidRequest
from app.discovery import registry
from app.discovery.contracts import Operation, SourceCandidate, SourceDescriptor
from app.discovery.models import SourceImport
from app.discovery.staging import stage_candidate

PROVIDER = "operator_seed_csv"
RIGHTS_POLICY = "operator-declared-v1"
MAX_BYTES = 256 * 1024
MAX_ROWS = 500
HEADER = ["school_name", "city", "locality", "source_reference"]
CITY = "Lahore"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|")
_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

DESCRIPTOR = SourceDescriptor(
    provider=PROVIDER,
    adapter_version="1.0.0",
    source_kind="seed_list",
    # Rights come from the operator's per-import declaration; this policy is reviewed yearly.
    terms_reference="operator-declaration:per-import",
    rights_policy_version=RIGHTS_POLICY,
    permitted_operations=frozenset({Operation.STORE_METADATA}),
    max_storage_class="metadata_only",
    retention_ttl=timedelta(days=365),
    request_quota=0,
    result_limit=MAX_ROWS,
    page_size=100,
    allowed_hostnames=frozenset(),
    requires_credentials=False,
    enabled=True,
    environments=frozenset({"development", "test", "production"}),
    last_reviewed_at=datetime(2026, 10, 23, tzinfo=UTC),
    reviewed_by="hermecious-p2.2-policy",
    supported_cities=frozenset({CITY}),
    supported_verticals=frozenset({"schools"}),
    attribution=None,
)


@dataclass
class SeedImportResult:
    import_id: str
    replayed: bool
    file_sha256: str
    row_count: int
    accepted_count: int
    rejected_count: int
    staged_new_count: int = 0
    staged_unchanged_count: int = 0
    staged_revised_count: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    rejected_rows: list[int] = field(default_factory=list)  # 1-based data row numbers, never cell content
    label: str = "OPERATOR-SEEDED: supplied by your organization, not independently verified"


def _cell(value: str, name: str, max_length: int, *, required: bool) -> str | None:
    if value.lstrip().startswith(_FORMULA_PREFIXES) or value.startswith(_FORMULA_PREFIXES):
        raise ValueError("formula_like")
    try:
        cleaned = policy.clean_text(value, name, max_length, required=required)
    except policy.PolicyViolation:
        raise ValueError("invalid_text") from None
    return cleaned or None


def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise InvalidRequest("seed file is larger than 256 KB")
    try:
        text = data.decode("utf-8-sig")  # accepts and strips a UTF-8 BOM
    except UnicodeDecodeError:
        raise InvalidRequest("seed file must be UTF-8") from None
    if "\x00" in text:
        raise InvalidRequest("seed file must be UTF-8 text")
    return text


def import_seed_csv(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    data: bytes,
    source_label: str,
    permission_declaration: str,
) -> SeedImportResult:
    source_service._require(actor, Capability.ADMINISTER)
    registry.check_descriptor(DESCRIPTOR, environment, now=clock.now())
    registry.require_operation(DESCRIPTOR, Operation.STORE_METADATA)
    try:
        label = policy.clean_text(source_label, "source_label", 200)
        declaration = policy.clean_text(permission_declaration, "permission_declaration", 1000)
    except policy.PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None
    if len(declaration) < 20:
        raise InvalidRequest("permission_declaration must say where the list came from and why you may use it")
    checksum = hashlib.sha256(data).hexdigest()
    text = _decode(data)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = [h.strip().lower() for h in next(reader, [])]
        rows = list(reader)
    except csv.Error:
        raise InvalidRequest("seed file is not valid CSV") from None
    if header not in (HEADER, [*HEADER, "external_key"]):
        raise InvalidRequest(f"header must be {','.join(HEADER)}[,external_key]")
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) > MAX_ROWS:
        raise InvalidRequest(f"seed file has more than {MAX_ROWS} rows")

    now = clock.now()
    import_id = db.scalar(
        insert(SourceImport)
        .values(
            id=uuid.uuid4(),
            organization_id=actor.organization_id,
            provider=PROVIDER,
            file_sha256=checksum,
            source_label=label,
            permission_declaration=declaration,
            row_count=len(rows),
            accepted_count=0,
            rejected_count=0,
            imported_by=actor.user_id,
            imported_at=now,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "provider", "file_sha256"])
        .returning(SourceImport.id)
    )
    if import_id is None:  # same bytes already imported (possibly concurrently): nothing changes
        db.rollback()
        prior = db.scalar(
            select(SourceImport).where(
                SourceImport.organization_id == actor.organization_id,
                SourceImport.provider == PROVIDER,
                SourceImport.file_sha256 == checksum,
            )
        )
        if prior is None:
            raise InvalidRequest("seed import could not be recorded")
        return SeedImportResult(str(prior.id), True, checksum, prior.row_count, prior.accepted_count,
                                prior.rejected_count)  # fmt: skip

    reasons: Counter[str] = Counter()
    rejected_rows: list[int] = []
    staged: Counter[str] = Counter()
    seen: set[str] = set()
    for number, row in enumerate(rows, start=1):
        try:
            if len(row) != len(header):
                raise ValueError("wrong_column_count")
            name = _cell(row[0], "school_name", 250, required=True)
            city = _cell(row[1], "city", 120, required=True)
            locality = _cell(row[2], "locality", 160, required=False)
            reference = _cell(row[3], "source_reference", 300, required=True)
            given_key = _cell(row[4], "external_key", 120, required=False) if len(header) == 5 else None
            if city is None or city.casefold() != CITY.casefold():
                raise ValueError("wrong_area")
            if given_key is not None and not _KEY.fullmatch(given_key):
                raise ValueError("invalid_external_key")
            identity = "\x1f".join([str(name).casefold(), CITY.casefold(), (locality or "").casefold(),
                                    str(reference)])  # fmt: skip
            key = given_key or "row-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
            if key in seen:
                raise ValueError("duplicate_row")
            candidate = SourceCandidate(
                provider=PROVIDER,
                external_key=key,
                display_name=str(name),
                city=CITY,
                vertical_slug="schools",
                locality=locality,
                observed_at=now,
                attribution=f"Operator seed: {label}"[:300],
            )
        except ValueError as exc:  # pydantic's ValidationError is a ValueError too
            code = str(exc) if str(exc) in _ROW_CODES else "invalid_row"
            reasons[code] += 1
            if len(rejected_rows) < 50:
                rejected_rows.append(number)
            continue
        seen.add(key)
        staged[
            stage_candidate(
                db,
                actor=actor,
                clock=clock,
                candidate=candidate,
                rights_policy_version=RIGHTS_POLICY,
                expires_at=None,
                source_import_id=import_id,
            )
        ] += 1

    accepted = len(seen)
    record = db.get(SourceImport, import_id)
    assert record is not None  # noqa: S101  # inserted above in this transaction
    record.accepted_count, record.rejected_count = accepted, len(rows) - accepted
    management._audit(
        db,
        actor,
        clock,
        "discovery.seed_import",
        import_id,
        {
            "provider": PROVIDER,
            "file_sha256": checksum,
            "rows": len(rows),
            "accepted": accepted,
            "rejected": len(rows) - accepted,
            "staged_new": staged["new"],
            "staged_revised": staged["revised"],
            "rejection_reasons": dict(sorted(reasons.items())),
        },
        target_type="source_import",
    )
    db.commit()
    return SeedImportResult(
        import_id=str(import_id),
        replayed=False,
        file_sha256=checksum,
        row_count=len(rows),
        accepted_count=accepted,
        rejected_count=len(rows) - accepted,
        staged_new_count=staged["new"],
        staged_unchanged_count=staged["unchanged"],
        staged_revised_count=staged["revised"],
        rejection_reasons=dict(sorted(reasons.items())),
        rejected_rows=rejected_rows,
    )


_ROW_CODES = frozenset(
    {"formula_like", "invalid_text", "wrong_column_count", "wrong_area", "invalid_external_key", "duplicate_row"}
)
