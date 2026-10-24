"""`/api/v1/accounts/*` (P1.4). Authentication, CSRF and roles come from `authorize_request`."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.accounts import management, service
from app.accounts.models import Account, ActionAudit, Vertical
from app.api.dependencies import AppClock
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request
from app.auth.models import Role
from app.core.errors import InvalidRequest, NotFound
from app.persistence.db import DbSession

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"], dependencies=[Depends(authorize_request)])
NO_STORE = {"Cache-Control": "no-store"}
CITIES = Literal["Lahore"]  # first market (blueprint §0); widen deliberately, not by accident
Status = Literal["discovered", "researching", "assessed", "shortlisted", "investigate", "nurture", "excluded"]
_IF_MATCH = re.compile(r'^(?:W/)?"?(\d{1,9})"?$')


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAccount(_Body):
    vertical: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")] = "schools"
    canonical_name: Annotated[str, Field(min_length=1, max_length=250)]
    city: CITIES = "Lahore"
    locality: Annotated[str, Field(min_length=1, max_length=160)] | None = None


class PatchAccount(_Body):
    expected_version: Annotated[int, Field(ge=1)] | None = None
    canonical_name: Annotated[str, Field(min_length=1, max_length=250)] | None = None
    locality: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    status: Status | None = None


class Archive(_Body):
    expected_version: Annotated[int, Field(ge=1)]


class NewSourceBody(_Body):
    provider: Annotated[str, Field(min_length=1, max_length=100)]
    source_url: Annotated[str, Field(min_length=1, max_length=2048)]
    storage_class: Literal["metadata_only", "derived_only", "full_allowed"]
    observed_at: AwareDatetime
    external_key: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    expires_at: AwareDatetime | None = None


class SourceChoice(_Body):
    source_id: uuid.UUID | None = None
    new: NewSourceBody | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "SourceChoice":
        if (self.source_id is None) == (self.new is None):
            raise ValueError("give exactly one of source_id or new")
        return self


class FactBody(_Body):
    claim_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")]
    value: dict[str, Any]
    verification_status: Literal["source_supported", "hypothesis"]
    confidence_label: Literal["strong", "moderate", "weak", "unknown"]
    observed_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    evidence_excerpt: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    source: SourceChoice | None = None

    def to_input(self) -> management.FactInput:
        new = self.source.new if self.source else None
        return management.FactInput(
            claim_type=self.claim_type,
            value=self.value,
            verification_status=self.verification_status,
            confidence_label=self.confidence_label,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            evidence_excerpt=self.evidence_excerpt,
            source_id=self.source.source_id if self.source else None,
            new_source=management.NewSource(**new.model_dump()) if new else None,
        )


class CorrectionBody(FactBody):
    reason: Annotated[str, Field(min_length=3, max_length=1000)]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def account_view(account: Account) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "vertical_id": str(account.vertical_id),
        "canonical_name": account.canonical_name,
        "normalized_name": account.normalized_name,
        "city": account.city,
        "locality": account.locality,
        "status": account.status,
        "version": account.version,
        "discovered_at": _iso(account.discovered_at),
        "updated_at": _iso(account.updated_at),
    }


def fact_view(fact: service.FactView) -> dict[str, Any]:
    source = fact.source
    return {
        "id": str(fact.id),
        "claim_type": fact.claim_type,
        "value": fact.value,
        "verification_status": fact.verification_status,
        "confidence_label": fact.confidence_label,
        "observed_at": _iso(fact.observed_at),
        "expires_at": _iso(fact.expires_at),
        "is_stale": fact.is_stale,
        "is_current": fact.is_current,
        "evidence_excerpt": fact.evidence_excerpt,
        "source": {
            "id": str(source.id),
            "provider": source.provider,
            "source_url": source.source_url,
            "permitted_storage_class": source.permitted_storage_class,
            "rights_policy_version": source.rights_policy_version,
            "observed_at": _iso(source.observed_at),
            "expires_at": _iso(source.expires_at),
        }
        if source
        else None,
        "supersedes_fact_id": str(fact.supersedes_fact_id) if fact.supersedes_fact_id else None,
        "superseded_by_fact_id": str(fact.superseded_by_fact_id) if fact.superseded_by_fact_id else None,
        "correction_reason": fact.correction_reason,
        "recorded_by": str(fact.recorded_by) if fact.recorded_by else None,
        "created_at": _iso(fact.created_at),
    }


def audit_view(audit: ActionAudit) -> dict[str, Any]:
    return {
        "action_type": audit.action_type,
        "actor_user_id": str(audit.actor_user_id),
        "details": audit.details_json,
        "request_id": audit.request_id,
        "recorded_at": _iso(audit.recorded_at),
    }


def _with_etag(body: dict[str, Any], version: int, status_code: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, headers={**NO_STORE, "ETag": f'"{version}"'})


def _expected_version(body_version: int | None, if_match: str | None) -> int:
    header_version = None
    if if_match is not None:
        match = _IF_MATCH.match(if_match.strip())
        if match is None:
            raise InvalidRequest("If-Match must be a quoted account version")
        header_version = int(match.group(1))
    if body_version is not None and header_version is not None and body_version != header_version:
        raise InvalidRequest("expected_version and If-Match disagree")
    version = body_version if body_version is not None else header_version
    if version is None:
        raise InvalidRequest("expected_version (or If-Match) is required")
    return version


@router.post("", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def create_account(body: CreateAccount, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    vertical = db.scalar(select(Vertical).where(Vertical.slug == body.vertical))
    if vertical is None:
        raise NotFound()
    account = management.create(
        db,
        actor=actor,
        clock=clock,
        vertical_id=vertical.id,
        name=body.canonical_name,
        city=body.city,
        locality=body.locality,
    )
    return _with_etag(account_view(account), account.version, 201)


@router.get("")
def list_accounts(
    actor: CurrentActor,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=management.MAX_PAGE)] = management.DEFAULT_PAGE,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    city: CITIES | None = None,
    vertical_id: uuid.UUID | None = None,
    status: Status | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> JSONResponse:
    page = management.list_accounts(
        db,
        actor=actor,
        filters=management.AccountFilters(city=city, vertical_id=vertical_id, status=status, q=q),
        limit=limit,
        cursor=cursor,
    )
    return JSONResponse(
        {"accounts": [account_view(a) for a in page.accounts], "next_cursor": page.next_cursor}, headers=NO_STORE
    )


@router.get("/{account_id}")
def get_account(account_id: uuid.UUID, actor: CurrentActor, db: DbSession, clock: AppClock) -> JSONResponse:
    detail = management.get_account(db, actor=actor, clock=clock, account_id=account_id)
    account = detail.evidence.account
    body = {
        **account_view(account),
        "aliases": detail.evidence.aliases,
        "facts": [fact_view(f) for f in detail.evidence.facts],
        "audits": [audit_view(a) for a in detail.audits],
    }
    return _with_etag(body, account.version)


@router.patch("/{account_id}")
@allow_roles(Role.OWNER, Role.OPERATOR)
def patch_account(
    account_id: uuid.UUID,
    body: PatchAccount,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
    if_match: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    sent = body.model_fields_set
    account = management.patch(
        db,
        actor=actor,
        clock=clock,
        account_id=account_id,
        expected_version=_expected_version(body.expected_version, if_match),
        canonical_name=body.canonical_name,
        locality=body.locality,
        clear_locality="locality" in sent and body.locality is None,
        status=body.status,
    )
    return _with_etag(account_view(account), account.version)


@router.post("/{account_id}/archive")
def archive_account(
    account_id: uuid.UUID, body: Archive, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    account = management.archive(
        db, actor=actor, clock=clock, account_id=account_id, expected_version=body.expected_version
    )
    return _with_etag(account_view(account), account.version)


@router.post("/{account_id}/facts", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def add_fact(
    account_id: uuid.UUID, body: FactBody, actor: CurrentActor, db: DbSession, clock: AppClock
) -> JSONResponse:
    fact = management.add_fact(db, actor=actor, clock=clock, account_id=account_id, data=body.to_input())
    return JSONResponse({"id": str(fact.id), "account_id": str(account_id)}, status_code=201, headers=NO_STORE)


@router.post("/{account_id}/facts/{fact_id}/corrections", status_code=201)
@allow_roles(Role.OWNER, Role.OPERATOR)
def correct_fact(
    account_id: uuid.UUID,
    fact_id: uuid.UUID,
    body: CorrectionBody,
    actor: CurrentActor,
    db: DbSession,
    clock: AppClock,
) -> JSONResponse:
    fact = management.correct_fact(
        db, actor=actor, clock=clock, account_id=account_id, fact_id=fact_id, reason=body.reason, data=body.to_input()
    )
    return JSONResponse(
        {"id": str(fact.id), "account_id": str(account_id), "supersedes_fact_id": str(fact_id)},
        status_code=201,
        headers=NO_STORE,
    )
