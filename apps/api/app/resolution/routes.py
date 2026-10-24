"""`/api/v1/identity/*` (P2.3): run the campus matcher and review its suggestions.

Owners and operators may run and decide; observers may read. Authentication,
CSRF and roles come from `authorize_request`. P2.4 renders these in the UI.
"""

import uuid
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.api.dependencies import AppClock
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.core.errors import NotFound
from app.discovery.models import DiscoveryCandidate
from app.persistence.db import DbSession
from app.resolution import service
from app.resolution.models import IdentityDecision, IdentitySuggestion

router = APIRouter(prefix="/api/v1/identity", tags=["identity"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Status = Literal["pending", "confirmed", "distinct", "deferred", "superseded", "undone", "reallocation_review"]


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: uuid.UUID
    action: service.Action
    expected_version: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=1000)]


def _sides(db: Session, org: uuid.UUID, suggestions: list[IdentitySuggestion]) -> dict[uuid.UUID, dict[str, Any]]:
    candidate_ids = {s.left_candidate_id for s in suggestions} | {
        s.right_candidate_id for s in suggestions if s.right_candidate_id
    }
    account_ids = {s.existing_account_id for s in suggestions if s.existing_account_id}
    sides: dict[uuid.UUID, dict[str, Any]] = {}
    if candidate_ids:
        for c in db.scalars(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.organization_id == org, DiscoveryCandidate.id.in_(candidate_ids)
            )
        ):
            sides[c.id] = {
                "id": str(c.id), "kind": "candidate", "provider": c.provider, "external_key": c.external_key,
                "display_name": c.display_name, "name_local": c.name_local, "city": c.city, "locality": c.locality,
                "location_precision": c.location_precision, "revision": c.revision, "status": c.status,
            }  # fmt: skip
    if account_ids:
        for a in db.scalars(select(Account).where(Account.organization_id == org, Account.id.in_(account_ids))):
            sides[a.id] = {"id": str(a.id), "kind": "account", "display_name": a.canonical_name, "city": a.city,
                           "locality": a.locality, "status": a.status}  # fmt: skip
    return sides


@router.post("/resolve")
@allow_roles(Role.OWNER, Role.OPERATOR)
def resolve(actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    report = service.run_resolution(db, actor=actor, clock=clock)
    return JSONResponse(asdict(report), headers=NO_STORE)


@router.get("/suggestions")
def list_suggestions(
    actor: CurrentActor,
    db: DbSession,
    status: Status | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> JSONResponse:
    query = (
        select(IdentitySuggestion)
        .where(IdentitySuggestion.organization_id == actor.organization_id)
        .order_by(IdentitySuggestion.created_at.desc(), IdentitySuggestion.id.desc())
        .limit(limit)
    )
    if status:
        query = query.where(IdentitySuggestion.status == status)
    rows = list(db.scalars(query))
    sides = _sides(db, actor.organization_id, rows)
    return JSONResponse({"items": [service.suggestion_view(s, sides) for s in rows]}, headers=NO_STORE)


@router.get("/suggestions/{suggestion_id}")
def get_suggestion(suggestion_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    org = actor.organization_id
    row = db.scalar(
        select(IdentitySuggestion).where(
            IdentitySuggestion.organization_id == org, IdentitySuggestion.id == suggestion_id
        )
    )
    if row is None:
        raise NotFound()
    decisions = db.scalars(
        select(IdentityDecision)
        .where(IdentityDecision.organization_id == org, IdentityDecision.suggestion_id == row.id)
        .order_by(IdentityDecision.recorded_at, IdentityDecision.id)
    )
    history = [
        {"id": str(d.id), "action": d.action, "prior_status": d.prior_status, "next_status": d.next_status,
         "reason": d.reason, "actor_user_id": str(d.actor_user_id), "held_fact_ids": d.held_fact_ids,
         "reverses_decision_id": str(d.reverses_decision_id) if d.reverses_decision_id else None,
         "recorded_at": d.recorded_at.isoformat()}
        for d in decisions
    ]  # fmt: skip
    view = service.suggestion_view(row, _sides(db, org, [row])) | {"decisions": history}
    return JSONResponse(view, headers=NO_STORE)


@router.post("/suggestions/{suggestion_id}/decisions")
@allow_roles(Role.OWNER, Role.OPERATOR)
def decide(
    suggestion_id: uuid.UUID, body: DecisionBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    result = service.decide(
        db,
        actor=actor,
        clock=clock,
        suggestion_id=suggestion_id,
        command_id=body.command_id,
        action=body.action,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    org = actor.organization_id
    view = service.suggestion_view(result.suggestion, _sides(db, org, [result.suggestion]))
    return JSONResponse(
        view
        | {
            "decision_id": str(result.decision_id),
            "replayed": result.replayed,
            "held_fact_ids": result.held_fact_ids,
            "link_id": str(result.link_id) if result.link_id else None,
        },
        headers=NO_STORE,
    )
