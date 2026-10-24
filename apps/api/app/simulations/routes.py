"""Dry-run API (P4.5): `/api/v1/campaigns/{id}/simulations`. Owners/operators start and cancel (CSRF); every role
reads. Every response carries "SIMULATION ONLY — 0 real messages sent". Nothing here can send."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.persistence.db import DbSession
from app.simulations import models, service

router = APIRouter(prefix="/api/v1/campaigns", tags=["simulations"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal[models.SCENARIOS] = "all_allow"  # type: ignore[valid-type]
    max_items: Annotated[int, Field(ge=1, le=service.MAX_ITEMS)] = service.MAX_ITEMS
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


def _detail(db: DbSession, run: models.SimulationRun) -> dict[str, object]:
    return service.view_run(db, run) | {"items": service.items(db, run)}


@router.post("/{campaign_id}/simulations")
@allow_roles(Role.OWNER, Role.OPERATOR)
def start(
    campaign_id: uuid.UUID, body: RunBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    run, created = service.create_run(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        campaign_id=campaign_id,
        scenario=body.scenario,
        max_items=body.max_items,
        idempotency_key=body.idempotency_key,
    )
    return JSONResponse(
        _detail(db, run) | {"replayed": not created}, status_code=201 if created else 200, headers=NO_STORE
    )


@router.get("/{campaign_id}/simulations")
def list_runs(campaign_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    runs = service.list_runs(db, actor.organization_id, campaign_id)
    return JSONResponse({"items": [service.view_run(db, r) for r in runs], "label": service.LABEL}, headers=NO_STORE)


@router.get("/{campaign_id}/simulations/{run_id}")
def get_run(campaign_id: uuid.UUID, run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    return JSONResponse(_detail(db, service.get_run(db, actor.organization_id, campaign_id, run_id)), headers=NO_STORE)


@router.post("/{campaign_id}/simulations/{run_id}/cancel")
@allow_roles(Role.OWNER, Role.OPERATOR)
def cancel(
    campaign_id: uuid.UUID, run_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    run = service.cancel_run(db, actor=actor, clock=clock, campaign_id=campaign_id, run_id=run_id)
    return JSONResponse(_detail(db, run), headers=NO_STORE)


@router.get("/{campaign_id}/simulations/{run_id}/export.csv")
def export(campaign_id: uuid.UUID, run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> Response:
    run = service.get_run(db, actor.organization_id, campaign_id, run_id)
    return Response(
        service.export_csv(db, run),
        media_type="text/csv; charset=utf-8",
        headers=NO_STORE | {"Content-Disposition": f'attachment; filename="simulation-{run.id}.csv"'},
    )
