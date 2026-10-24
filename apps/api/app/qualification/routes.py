"""Qualification API (P3.3). Owners/operators assess and override (CSRF); every role reads.

`contact_now` is a research priority only: channel eligibility is never evaluated here, and nothing is sent.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.persistence.db import DbSession
from app.qualification import service

router = APIRouter(prefix="/api/v1/accounts", tags=["qualification"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Level = Literal["strong", "moderate", "weak", "unknown"]


class AssessBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: uuid.UUID | None = None


class Dimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_fit: Level | None = None
    need_evidence: Level | None = None
    accessibility: Level | None = None
    delivery_fit: Level | None = None


class OverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
    decision: Literal["contact_now", "investigate", "nurture", "exclude"] | None = None
    dimensions: Dimensions = Dimensions()
    evidence_fact_ids: Annotated[list[uuid.UUID], Field(max_length=10)] = []


@router.post("/{account_id}/assess")
@allow_roles(Role.OWNER, Role.OPERATOR)
def assess(
    account_id: uuid.UUID, body: AssessBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    row, created = service.assess(db, actor=actor, clock=clock, account_id=account_id, offer_id=body.offer_id)
    return JSONResponse(service.view(row) | {"created": created}, status_code=201 if created else 200, headers=NO_STORE)


@router.get("/{account_id}/assessments")
def read(account_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    return JSONResponse(service.latest(db, actor.organization_id, account_id, clock.now()), headers=NO_STORE)


@router.post("/{account_id}/assessments/{assessment_id}/override", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def override(
    account_id: uuid.UUID, assessment_id: uuid.UUID, body: OverrideBody, actor: CurrentActor, db: DbSession,
    clock: AppClock,
) -> JSONResponse:  # fmt: skip
    dims = {k: v for k, v in body.dimensions.model_dump().items() if v is not None}
    row = service.override(
        db, actor=actor, clock=clock, account_id=account_id, assessment_id=assessment_id,
        expected_revision=body.expected_revision, reason=body.reason, decision=body.decision, dimensions=dims,
        evidence_fact_ids=body.evidence_fact_ids,
    )  # fmt: skip
    return JSONResponse(service.view(row), status_code=201, headers=NO_STORE)
