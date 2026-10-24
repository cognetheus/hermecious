"""School operations brief API (P3.2). Owners/operators generate (CSRF); every role reads."""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import AppClock
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.persistence.db import DbSession
from app.signals import service

router = APIRouter(prefix="/api/v1", tags=["school-signals"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}


@router.post("/accounts/{account_id}/school-signals/generate")
@allow_roles(Role.OWNER, Role.OPERATOR)
def generate(account_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    snapshot, created = service.generate(db, actor=actor, clock=clock, account_id=account_id)
    body = service.snapshot_view(db, snapshot, clock.now()) | {"created": created}
    return JSONResponse(body, status_code=201 if created else 200, headers=NO_STORE)


@router.get("/accounts/{account_id}/school-signals")
def read_latest(account_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    return JSONResponse(service.latest(db, actor.organization_id, account_id, clock.now()), headers=NO_STORE)


@router.get("/school-signal-snapshots/{snapshot_id}")
def read_snapshot(snapshot_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    snapshot = service.get_snapshot(db, actor.organization_id, snapshot_id)
    return JSONResponse(service.snapshot_view(db, snapshot, clock.now()), headers=NO_STORE)
