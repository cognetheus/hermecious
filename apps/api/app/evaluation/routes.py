"""Evidence quality evaluation API (P3.4). Owners/operators create, adjudicate, remediate and finalize (CSRF);
every role reads. Reports carry rights-safe summaries only (no excerpts, no reviewer contact details)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencies import AppClock, AppSettings
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.evaluation import service
from app.evaluation.models import EvidenceEvalItem, EvidenceEvalRun, EvidenceEvalVerdict
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/evidence-evals", tags=["evaluation"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["baseline", "post_remediation"] = "baseline"
    seed: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    idempotency_key: Key
    baseline_run_id: uuid.UUID | None = None
    allow_synthetic: bool = False


class VerdictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["supported", "unsupported", "contradicted", "stale", "unverifiable"]
    reason: Annotated[str, Field(min_length=3, max_length=1000)]
    expected_version: Annotated[int, Field(ge=1)]


class RemediateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(min_length=3, max_length=600)]


class FinalizeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Field(ge=1)]


@router.get("/gate")
def quality_gate(actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    return JSONResponse(service.gate(db, actor.organization_id, clock.now()), headers=NO_STORE)


@router.post("", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create(
    body: CreateBody, actor: CurrentActor, db: DbSession, clock: AppClock, settings: AppSettings
) -> JSONResponse:
    run, created = service.create_run(
        db,
        actor=actor,
        clock=clock,
        environment=settings.environment,
        kind=body.kind,
        seed=body.seed,
        idempotency_key=body.idempotency_key,
        baseline_run_id=body.baseline_run_id,
        allow_synthetic=body.allow_synthetic,
    )
    view = service.run_view(db, run, with_items=False) | {"created": created}
    return JSONResponse(view, status_code=201 if created else 200, headers=NO_STORE)


@router.get("")
def list_runs(actor: CurrentActor, db: DbSession) -> JSONResponse:
    runs = db.scalars(
        select(EvidenceEvalRun)
        .where(EvidenceEvalRun.organization_id == actor.organization_id)
        .order_by(EvidenceEvalRun.created_at.desc())
        .limit(20)
    )
    return JSONResponse({"items": [service.run_view(db, r, with_items=False) for r in runs]}, headers=NO_STORE)


@router.get("/{run_id}")
def get_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    run = service._run(db, actor.organization_id, run_id)
    return JSONResponse(service.run_view(db, run, with_items=True), headers=NO_STORE)


@router.get("/{run_id}/report")
def report(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    """Export: counts, fingerprint and per-item verdict history (reviewer ids only; no excerpts or contacts)."""
    run = service._run(db, actor.organization_id, run_id)
    view = service.run_view(db, run, with_items=True)
    history: dict[str, list[dict[str, object]]] = {}
    for v in db.scalars(
        select(EvidenceEvalVerdict)
        .where(
            EvidenceEvalVerdict.organization_id == actor.organization_id,
            EvidenceEvalVerdict.item_id.in_(select(EvidenceEvalItem.id).where(EvidenceEvalItem.run_id == run.id)),
        )
        .order_by(EvidenceEvalVerdict.revision)
    ):
        history.setdefault(str(v.item_id), []).append(
            {
                "revision": v.revision,
                "verdict": v.verdict,
                "reason": v.reason,
                "reviewer_id": str(v.reviewer_id),
                "at": v.created_at.isoformat(),
            }
        )
    for item in view["item_list"]:
        item["verdict_history"] = history.get(item["id"], [])
    return JSONResponse(view | {"report_version": "evidence-eval-report-1"}, headers=NO_STORE)


@router.post("/{run_id}/items/{item_id}/verdict")
@allow_roles(Role.OWNER, Role.OPERATOR)
def verdict(
    run_id: uuid.UUID, item_id: uuid.UUID, body: VerdictBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    item = service.adjudicate(
        db,
        actor=actor,
        clock=clock,
        run_id=run_id,
        item_id=item_id,
        verdict=body.verdict,
        reason=body.reason,
        expected_version=body.expected_version,
    )
    return JSONResponse({"id": str(item.id), "verdict": item.verdict, "version": item.version}, headers=NO_STORE)


@router.post("/{run_id}/items/{item_id}/remediate", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def remediate(
    run_id: uuid.UUID, item_id: uuid.UUID, body: RemediateBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    link = service.remediate(db, actor=actor, clock=clock, run_id=run_id, item_id=item_id, reason=body.reason)
    return JSONResponse(
        {"item_id": str(link.item_id), "correction_fact_id": str(link.correction_fact_id)},
        status_code=201,
        headers=NO_STORE,
    )


@router.post("/{run_id}/finalize")
@allow_roles(Role.OWNER, Role.OPERATOR)
def finalize(
    run_id: uuid.UUID, body: FinalizeBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    run = service.finalize(db, actor=actor, clock=clock, run_id=run_id, expected_version=body.expected_version)
    return JSONResponse(service.run_view(db, run, with_items=False), headers=NO_STORE)
