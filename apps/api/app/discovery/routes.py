"""`/api/v1/discovery/*` (P2.2): operator seed import and the staged-candidate list.

Authentication, CSRF and roles come from `authorize_request` (unsafe methods
are owner-only). There is deliberately no endpoint that starts a live source
run or accepts a URL; P2.4 owns run management.
"""

import base64
import binascii
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select

from app.accounts.models import SourceRecord
from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, authorize_request
from app.core.errors import InvalidRequest
from app.discovery import seed_import
from app.discovery.models import DiscoveryCandidate
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
ORIGIN = {"operator_seed_csv": "operator_seeded", "osm_overpass_schools": "map_listing"}


class SeedImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_label: Annotated[str, Field(min_length=1, max_length=200)]
    permission_declaration: Annotated[str, Field(min_length=20, max_length=1000)]
    csv_text: Annotated[str, Field(min_length=1, max_length=seed_import.MAX_BYTES)]


@router.post("/seed-imports", status_code=201)
def create_seed_import(
    body: SeedImportBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    result = seed_import.import_seed_csv(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        data=body.csv_text.encode("utf-8"),
        source_label=body.source_label,
        permission_declaration=body.permission_declaration,
    )
    return JSONResponse(asdict(result), status_code=200 if result.replayed else 201, headers=NO_STORE)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _cursor(row: DiscoveryCandidate) -> str:
    return base64.urlsafe_b64encode(f"{row.created_at.isoformat()}|{row.id}".encode()).decode()


def _parse_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, ident = base64.urlsafe_b64decode(raw.encode()).decode().split("|")
        return datetime.fromisoformat(created), uuid.UUID(ident)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise InvalidRequest("cursor is invalid") from None


def candidate_view(row: DiscoveryCandidate, source_url: str | None, now: datetime) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "verification": "unverified",  # a listing is never a verified school, prospect or contact
        "origin": ORIGIN.get(row.provider, "fixture"),
        "provider": row.provider,
        "external_key": row.external_key,
        "display_name": row.display_name,
        "name_local": row.name_local,
        "city": row.city,
        "locality": row.locality,
        "latitude": float(row.latitude) if row.latitude is not None else None,
        "longitude": float(row.longitude) if row.longitude is not None else None,
        "location_precision": row.location_precision,
        "source_url": source_url,
        "observed_at": _iso(row.observed_at),
        "upstream_timestamp": _iso(row.upstream_timestamp),
        "rights_policy_version": row.rights_policy_version,
        "attribution": row.attribution,
        "expires_at": _iso(row.expires_at),
        "expired": row.expires_at is not None and row.expires_at <= now,
        "status": row.status,
        "revision": row.revision,
    }


@router.get("/candidates")
def list_candidates(
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    provider: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["unreviewed", "admitted", "rejected"] | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> JSONResponse:
    query = (
        select(DiscoveryCandidate, SourceRecord.source_url)
        .outerjoin(
            SourceRecord,
            and_(
                SourceRecord.organization_id == DiscoveryCandidate.organization_id,
                SourceRecord.id == DiscoveryCandidate.source_record_id,
            ),
        )
        .where(DiscoveryCandidate.organization_id == actor.organization_id)
        .order_by(DiscoveryCandidate.created_at.desc(), DiscoveryCandidate.id.desc())
        .limit(limit + 1)
    )
    if provider:
        query = query.where(DiscoveryCandidate.provider == provider)
    if status:
        query = query.where(DiscoveryCandidate.status == status)
    if cursor:
        created, ident = _parse_cursor(cursor)
        query = query.where(
            or_(
                DiscoveryCandidate.created_at < created,
                and_(DiscoveryCandidate.created_at == created, DiscoveryCandidate.id < ident),
            )
        )
    rows = [(row, url) for row, url in db.execute(query)]
    now = clock.now()
    page = rows[:limit]
    return JSONResponse(
        {
            "items": [candidate_view(row, url, now) for row, url in page],
            "next_cursor": _cursor(page[-1][0]) if len(rows) > limit else None,
        },
        headers=NO_STORE,
    )
