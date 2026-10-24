"""Job receipts and owner diagnostics (P1.5). Payloads are never returned."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.auth.dependencies import Capability, CurrentActor, authorize_request, require_capability
from app.auth.service import Actor
from app.core.errors import NotFound
from app.jobs.models import Job, JobStatus
from app.jobs.runner import db_now, queue_metrics
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1", tags=["jobs"], dependencies=[Depends(authorize_request)])
Administrator = Annotated[Actor, Depends(require_capability(Capability.ADMINISTER))]
NO_STORE = {"Cache-Control": "no-store"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def job_view(job: Job) -> dict[str, Any]:
    iso = _iso
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "schema_version": job.job_schema_version,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": iso(job.available_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "last_error_class": job.last_error_class,
        "created_at": iso(job.created_at),
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> JSONResponse:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.organization_id == actor.organization_id))
    if job is None:
        raise NotFound()
    return JSONResponse(job_view(job), headers=NO_STORE)


@router.get("/ops/jobs")
def job_diagnostics(actor: Administrator, db: DbSession) -> JSONResponse:
    """Owner-only backlog and dead-letter view for this organization (no payloads)."""
    dead = db.scalars(
        select(Job)
        .where(Job.organization_id == actor.organization_id, Job.status == JobStatus.DEAD)
        .order_by(Job.finished_at.desc())
        .limit(50)
    )
    org_metrics = queue_metrics(db, db_now(db), organization_id=actor.organization_id)
    return JSONResponse({"metrics": org_metrics, "dead": [job_view(j) for j in dead]}, headers=NO_STORE)
