"""`/api/v1/discovery/*`: seed import and staged candidates (P2.2); runs and reviewer admission (P2.4).

Authentication, CSRF and roles come from `authorize_request` (unsafe methods
are owner-only unless widened with `allow_roles`). A run names a provider the
server resolves to a reviewed descriptor and configured area. No endpoint
accepts a URL, a query string for a provider, or a bounding box.
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
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.core.errors import InvalidRequest
from app.discovery import runs, seed_import
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


# --- P2.4 runs ----------------------------------------------------------------------------------------------

IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Annotated[str, Field(min_length=1, max_length=100)]
    budget: runs.RunBudget = runs.RunBudget()
    idempotency_key: IdempotencyKey


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: runs.ReviewAction
    expected_version: Annotated[int, Field(ge=1)]
    idempotency_key: IdempotencyKey
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
    existing_account_id: uuid.UUID | None = None


@router.get("/sources")
def list_sources(actor: CurrentActor, clock: AppClock, settings: AppSettings) -> JSONResponse:
    """Only providers that pass policy right now, with their configured area and rights summary."""
    items = [
        {
            "provider": o.provider, "label": o.label, "area_label": o.area_label, "synthetic": o.synthetic,
            "rights_policy_version": o.descriptor.rights_policy_version, "attribution": o.descriptor.attribution,
            "licence_reference": o.descriptor.licence_reference, "storage": o.descriptor.max_storage_class,
            "retention_days": o.descriptor.retention_ttl.days, "max_candidates": min(30, o.descriptor.result_limit),
            "request_quota": o.descriptor.request_quota,
        }
        for o in runs.available_sources(settings, clock.now())
    ]  # fmt: skip
    ceilings = runs.RunBudget().model_dump()
    return JSONResponse({"sources": items, "budget_ceilings": ceilings, "city": runs.CITY}, headers=NO_STORE)


@router.post("/runs", status_code=202)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_run(
    body: RunBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    run, created = runs.create_run(
        db, actor=actor, clock=clock, settings=settings, provider=body.provider, budget=body.budget,
        idempotency_key=body.idempotency_key,
    )  # fmt: skip
    return JSONResponse(runs.run_view(db, run) | {"replayed": not created}, status_code=202, headers=NO_STORE)


@router.get("/runs")
def list_runs(
    actor: CurrentActor,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> JSONResponse:
    rows = runs.list_runs(db, actor.organization_id, limit, _parse_cursor(cursor) if cursor else None)
    page = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(f"{page[-1].created_at.isoformat()}|{page[-1].id}".encode()).decode()
        if len(rows) > limit
        else None
    )
    return JSONResponse({"items": [runs.run_view(db, r) for r in page], "next_cursor": next_cursor}, headers=NO_STORE)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse(runs.run_view(db, runs.get_run(db, actor.organization_id, run_id)), headers=NO_STORE)


@router.get("/runs/{run_id}/candidates")
def get_run_candidates(run_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    run = runs.get_run(db, actor.organization_id, run_id)
    items = runs.run_candidates_view(db, run, clock.now())
    return JSONResponse({"items": items, "attribution": run.attribution, "synthetic": run.provider ==
                         "fixture_lahore_schools"}, headers=NO_STORE)  # fmt: skip


@router.post("/runs/{run_id}/cancel")
@allow_roles(Role.OWNER, Role.OPERATOR)
def cancel_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    run = runs.cancel_run(db, actor=actor, clock=clock, run_id=run_id)
    return JSONResponse(runs.run_view(db, run), headers=NO_STORE)


@router.post("/runs/{run_id}/candidates/{candidate_id}/decision")
@allow_roles(Role.OWNER, Role.OPERATOR)
def review_candidate(
    run_id: uuid.UUID, candidate_id: uuid.UUID, body: ReviewBody, actor: CurrentActor, db: DbSession,
    clock: AppClock, settings: AppSettings,
) -> JSONResponse:  # fmt: skip
    result = runs.review_candidate(
        db, actor=actor, clock=clock, environment=settings.environment, run_id=run_id, candidate_id=candidate_id,
        action=body.action, expected_version=body.expected_version, idempotency_key=body.idempotency_key,
        reason=body.reason, existing_account_id=body.existing_account_id,
    )  # fmt: skip
    row = result.run_candidate
    return JSONResponse(
        {
            "candidate_id": str(candidate_id), "review_status": row.display_status, "version": row.version,
            "account_id": str(result.account_id) if result.account_id else None, "replayed": result.replayed,
            "converged": result.converged, "decision_id": str(result.decision_id),
        },
        headers=NO_STORE,
    )  # fmt: skip
