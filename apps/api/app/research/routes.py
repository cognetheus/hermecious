"""Research API (P3.1): account research runs over associated sources, and claim review.

Owners and operators may start, cancel and review (CSRF); observers read.
The request carries source record ids only, never URLs, hostnames or queries.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.persistence.db import DbSession
from app.research import service
from app.research.models import ResearchRun

router = APIRouter(prefix="/api/v1", tags=["research"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=service.MAX_SOURCES)]
    idempotency_key: Key
    budget: service.ResearchBudget = service.ResearchBudget()


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject"]
    expected_version: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
    idempotency_key: Key
    confidence_label: Literal["strong", "moderate", "weak"] = "moderate"


@router.get("/accounts/{account_id}/research-sources")
def research_sources(
    account_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    service._account(db, actor.organization_id, account_id)
    items = service.sources_view(db, actor.organization_id, account_id, settings.environment, clock.now())
    return JSONResponse({"items": items, "max_sources": service.MAX_SOURCES}, headers=NO_STORE)


@router.post("/accounts/{account_id}/research-runs", status_code=202)
@allow_roles(Role.OWNER, Role.OPERATOR)
def start_research(
    account_id: uuid.UUID, body: ResearchBody, actor: CurrentActor, db: DbSession, clock: AppClock,
    settings: AppSettings,
) -> JSONResponse:  # fmt: skip
    run, created = service.create_run(
        db, actor=actor, clock=clock, environment=settings.environment, account_id=account_id,
        source_record_ids=body.source_record_ids, idempotency_key=body.idempotency_key, budget=body.budget,
    )  # fmt: skip
    return JSONResponse(service.run_view(run) | {"replayed": not created}, status_code=202, headers=NO_STORE)


@router.get("/accounts/{account_id}/research-runs")
def list_research(
    account_id: uuid.UUID, actor: CurrentActor, db: DbSession, limit: Annotated[int, Query(ge=1, le=20)] = 10
) -> JSONResponse:
    service._account(db, actor.organization_id, account_id)
    runs = db.scalars(
        select(ResearchRun)
        .where(ResearchRun.organization_id == actor.organization_id, ResearchRun.account_id == account_id)
        .order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc())
        .limit(limit)
    )
    return JSONResponse({"items": [service.run_view(r) for r in runs]}, headers=NO_STORE)


@router.get("/research-runs/{run_id}")
def get_research(
    run_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    run = service.get_run(db, actor.organization_id, run_id)
    return JSONResponse(service.run_detail(db, run, settings.environment, clock.now()), headers=NO_STORE)


@router.post("/research-runs/{run_id}/cancel")
@allow_roles(Role.OWNER, Role.OPERATOR)
def cancel_research(run_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    return JSONResponse(service.run_view(service.cancel_run(db, actor=actor, clock=clock, run_id=run_id)),
                        headers=NO_STORE)  # fmt: skip


@router.post("/research-claims/{claim_id}/review")
@allow_roles(Role.OWNER, Role.OPERATOR)
def review_claim(
    claim_id: uuid.UUID, body: ReviewBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    result = service.review_claim(
        db, actor=actor, clock=clock, environment=settings.environment, claim_id=claim_id, action=body.action,
        expected_version=body.expected_version, reason=body.reason, idempotency_key=body.idempotency_key,
        confidence_label=body.confidence_label,
    )  # fmt: skip
    return JSONResponse(
        {"id": str(result.claim.id), "status": result.claim.status, "version": result.claim.version,
         "fact_id": str(result.fact_id) if result.fact_id else None, "replayed": result.replayed},
        headers=NO_STORE,
    )  # fmt: skip
