"""Idempotent, organization-scoped staging of review candidates (P2.2).

One row per (organization, provider, external_key). A replay of identical
content changes nothing; changed permitted fields bump `revision` and leave an
audit row with both digests. Staging never creates accounts, facts or contacts.
"""

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.auth.service import Actor
from app.core.clock import Clock
from app.discovery.contracts import SourceCandidate
from app.discovery.models import DiscoveryCandidate

StageOutcome = Literal["new", "revised", "unchanged"]


def _coordinate(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(f"{value:.6f}")


def _fields(candidate: SourceCandidate) -> dict[str, object]:
    """The rights-permitted listing fields; also what the content digest covers."""
    return {
        "display_name": candidate.display_name,
        "name_local": candidate.name_local,
        "city": candidate.city,
        "locality": candidate.locality,
        "latitude": _coordinate(candidate.latitude),
        "longitude": _coordinate(candidate.longitude),
        "location_precision": candidate.location_precision,
    }


def payload_digest(candidate: SourceCandidate) -> str:
    canonical = json.dumps({k: (str(v) if v is not None else None) for k, v in _fields(candidate).items()},
                           sort_keys=True, ensure_ascii=False)  # fmt: skip
    return hashlib.sha256(canonical.encode()).hexdigest()


def stage_candidate(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    candidate: SourceCandidate,
    rights_policy_version: str,
    expires_at: datetime | None,
    source_record_id: uuid.UUID | None = None,
    source_import_id: uuid.UUID | None = None,
) -> StageOutcome:
    """Caller commits. Safe under concurrent replays (ON CONFLICT + row lock)."""
    now = clock.now()
    digest = payload_digest(candidate)
    fields = _fields(candidate)
    provenance = {
        "source_record_id": source_record_id,
        "source_import_id": source_import_id,
        "observed_at": candidate.observed_at,
        "upstream_timestamp": candidate.upstream_timestamp,
        "rights_policy_version": rights_policy_version,
        "attribution": candidate.attribution,
        "expires_at": expires_at,
    }
    inserted = db.scalar(
        insert(DiscoveryCandidate)
        .values(
            id=uuid.uuid4(),
            organization_id=actor.organization_id,
            provider=candidate.provider,
            external_key=str(candidate.external_key),
            status="unreviewed",
            revision=1,
            payload_digest=digest,
            created_at=now,
            updated_at=now,
            **fields,
            **provenance,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "provider", "external_key"])
        .returning(DiscoveryCandidate.id)
    )
    if inserted is not None:
        return "new"
    row = db.scalar(
        select(DiscoveryCandidate)
        .where(
            DiscoveryCandidate.organization_id == actor.organization_id,
            DiscoveryCandidate.provider == candidate.provider,
            DiscoveryCandidate.external_key == str(candidate.external_key),
        )
        .with_for_update()
    )
    if row is None or row.payload_digest == digest:
        return "unchanged"  # identical content: no timestamp refresh, no audit noise
    previous = row.payload_digest
    for name, value in {**fields, **provenance}.items():
        if name in ("source_record_id", "source_import_id") and value is None:
            continue  # keep existing provenance links; never drop them on revision
        setattr(row, name, value)
    row.payload_digest = digest
    row.revision += 1
    row.updated_at = now
    management._audit(
        db,
        actor,
        clock,
        "discovery.candidate_revised",
        row.id,
        {"provider": row.provider, "revision": row.revision, "previous_digest": previous, "digest": digest},
        target_type="discovery_candidate",
    )
    return "revised"
