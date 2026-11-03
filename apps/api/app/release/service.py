"""Readiness assessments, owner attestations and pilot authorizations (P5.5, ADR-030). Nothing here sends.

- `evaluate` stores an immutable, digest-bound, 24-hour assessment computed by `readiness.checks`.
- `attest` records an owner's human decision with an evidence reference (append-only, 90 days).
- `authorize` is a separate owner act: it needs a fresh `ready_for_operator_review` assessment, an exact typed
  acknowledgement, a cap of at most 3 messages a day and an expiry of at most 14 days. It still sends nothing; the
  deploy-time live gate and every per-send check remain independent.
- `pause` (human takeover, quality alert, investigation), `resume` and `revoke` stop unsent work immediately.
- `sync_production_catalog` is a read-only GET of Meta's template catalog for the production connection.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.settings import Settings
from app.release import readiness
from app.release.models import ATTESTATION_KINDS, PilotAuthorization, ReadinessAssessment, ReadinessAttestation
from app.whatsapp import service as connections
from app.whatsapp import transport as wa
from app.whatsapp.models import ProviderConnection, ProviderTemplate

PILOT_ACK = "I authorize a manual, low-volume WhatsApp pilot to opted-in contacts only."
MAX_PILOT_DAYS = 14
PAUSE_REASONS = ("human_takeover", "quality_alert", "investigation", "opt_out_review")
# Set only by the pilot's circuit breaker (auth or quota errors from Meta); an owner resumes after investigating.
AUTOMATIC_PAUSE_REASONS = ("provider_error",)
BANNER = "PRODUCTION OUTBOUND DISABLED UNTIL SEPARATE OPERATOR GO-LIVE"


def live_gate(settings: Settings) -> str | None:
    """Why the deploy-time live gate is closed (None = open). Independent of every database record."""
    if settings.environment != "production":
        return "not_production_environment"
    if settings.whatsapp_mode != "production":
        return "not_production_mode"
    if not settings.live_outbound_enabled:
        return "live_outbound_disabled"
    return None


# --- assessments ---------------------------------------------------------------------------------------------------


def evaluate(db: Session, *, actor: Actor, clock: Clock, settings: Settings) -> ReadinessAssessment:
    account_service._require(actor, Capability.ADMINISTER)
    org, now = actor.organization_id, clock.now()
    results = readiness.checks(db, org, settings, now)
    ident = readiness.identity(db, org, settings)
    row = ReadinessAssessment(
        organization_id=org, snapshot_version=readiness.SNAPSHOT_VERSION, status=readiness.status_of(results),
        digest=readiness.digest(results, ident, settings), checks_json=[c.as_dict() for c in results],
        identity_json=ident, environment=settings.environment, build_sha=settings.build_sha,
        checked_by=actor.user_id, checked_at=now, expires_at=now + readiness.VALIDITY,
    )  # fmt: skip
    db.add(row)
    db.flush()
    management._audit(db, actor, clock, "release.readiness_evaluated", row.id,
                      {"status": row.status, "digest": row.digest}, target_type="readiness_assessment")  # fmt: skip
    db.commit()
    return row


def latest(db: Session, org: uuid.UUID) -> ReadinessAssessment | None:
    return db.scalar(
        select(ReadinessAssessment)
        .where(ReadinessAssessment.organization_id == org)
        .order_by(ReadinessAssessment.checked_at.desc(), ReadinessAssessment.id.desc())
        .limit(1)
    )


def current_digest(db: Session, org: uuid.UUID, settings: Settings, now: datetime) -> tuple[str, str]:
    """(status, digest) recomputed now, for invalidation checks."""
    results = readiness.checks(db, org, settings, now)
    return readiness.status_of(results), readiness.digest(results, readiness.identity(db, org, settings), settings)


def assessment_view(row: ReadinessAssessment, now: datetime) -> dict[str, Any]:
    return {
        "id": str(row.id), "status": row.status, "digest": row.digest, "checks": row.checks_json,
        "identity": row.identity_json, "environment": row.environment, "build_sha": row.build_sha,
        "checked_at": row.checked_at.isoformat(), "expires_at": row.expires_at.isoformat(),
        "fresh": now < row.expires_at, "grants_sending": False, "banner": BANNER,
    }  # fmt: skip


# --- attestations --------------------------------------------------------------------------------------------------


def attest(
    db: Session, *, actor: Actor, clock: Clock, kind: str, statement: str, evidence_ref: str
) -> ReadinessAttestation:
    """Owner-only record of a human decision. The evidence reference is required; it is never a bare boolean."""
    account_service._require(actor, Capability.ADMINISTER)
    if kind not in ATTESTATION_KINDS:
        raise Unprocessable("ATTESTATION_KIND_UNKNOWN")
    now = clock.now()
    row = ReadinessAttestation(
        organization_id=actor.organization_id, kind=kind, statement=" ".join(statement.split()),
        evidence_ref=evidence_ref.strip(), attested_by=actor.user_id, attested_at=now,
        expires_at=now + readiness.ATTESTATION_VALIDITY,
    )  # fmt: skip
    db.add(row)
    db.flush()
    management._audit(db, actor, clock, "release.attested", row.id, {"kind": kind, "evidence_ref": row.evidence_ref},
                      target_type="readiness_attestation")  # fmt: skip
    db.commit()
    return row


def attestations_view(db: Session, org: uuid.UUID, now: datetime) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ReadinessAttestation)
        .where(ReadinessAttestation.organization_id == org)
        .order_by(ReadinessAttestation.attested_at.desc())
        .limit(50)
    )
    return [
        {"id": str(r.id), "kind": r.kind, "statement": r.statement, "evidence_ref": r.evidence_ref,
         "attested_at": r.attested_at.isoformat(), "expires_at": r.expires_at.isoformat(),
         "current": now < r.expires_at}
        for r in rows
    ]  # fmt: skip


# --- pilot authorization -------------------------------------------------------------------------------------------


def _authorization(db: Session, org: uuid.UUID, auth_id: uuid.UUID) -> PilotAuthorization:
    row = db.scalar(
        select(PilotAuthorization)
        .where(PilotAuthorization.organization_id == org, PilotAuthorization.id == auth_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFound()
    return row


def authorize(
    db: Session, *, actor: Actor, clock: Clock, settings: Settings, assessment_id: uuid.UUID, acknowledgement: str,
    purpose: str, max_per_day: int, days: int,
) -> PilotAuthorization:  # fmt: skip
    account_service._require(actor, Capability.ADMINISTER)
    org, now = actor.organization_id, clock.now()
    if acknowledgement.strip() != PILOT_ACK:
        raise Unprocessable("ACKNOWLEDGEMENT_MISMATCH: type the acknowledgement exactly")
    if not 1 <= max_per_day <= 3 or not 1 <= days <= MAX_PILOT_DAYS or purpose not in ("marketing", "utility"):
        raise Unprocessable("PILOT_LIMITS: at most 3 messages a day, at most 14 days, purpose marketing or utility")
    assessment = db.scalar(
        select(ReadinessAssessment).where(
            ReadinessAssessment.organization_id == org, ReadinessAssessment.id == assessment_id
        )
    )
    if assessment is None:
        raise NotFound()  # another organization's report id is indistinguishable from a missing one
    if assessment.status != "ready_for_operator_review" or now >= assessment.expires_at:
        raise Conflict(f"the assessment is {assessment.status} or expired; a pilot needs a fresh ready assessment")
    status, digest = current_digest(db, org, settings, now)
    if (status, digest) != (assessment.status, assessment.digest):
        raise Conflict("readiness changed since this assessment; evaluate again")
    connection = connections.connection_for(db, org, settings)
    row = PilotAuthorization(
        organization_id=org, provider_connection_id=connection.connection_id, assessment_id=assessment.id,
        assessment_digest=assessment.digest, purpose=purpose, max_per_day=max_per_day, acknowledgement=PILOT_ACK,
        status="active", authorized_by=actor.user_id, created_at=now, expires_at=now + timedelta(days=days),
        updated_at=now, version=1,
    )  # fmt: skip
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("a pilot authorization is already active or paused for this connection") from None
    management._audit(db, actor, clock, "release.pilot_authorized", row.id,
                      {"assessment_id": str(assessment.id), "purpose": purpose, "max_per_day": max_per_day,
                       "expires_at": row.expires_at.isoformat()}, target_type="pilot_authorization")  # fmt: skip
    db.commit()
    return row


def set_status(
    db: Session, *, actor: Actor, clock: Clock, auth_id: uuid.UUID, action: str, reason: str | None = None
) -> PilotAuthorization:
    """`pause` (with a reason), `resume` or `revoke` (final). Owner-only; audited."""
    account_service._require(actor, Capability.ADMINISTER)
    row = _authorization(db, actor.organization_id, auth_id)
    now = clock.now()
    if row.status == "revoked":
        db.rollback()
        raise Conflict("this pilot authorization is revoked")
    if action == "pause":
        if reason not in PAUSE_REASONS:
            raise Unprocessable("PAUSE_REASON_UNKNOWN")
        row.status, row.pause_reason = "paused", reason
    elif action == "resume":
        if row.status != "paused":
            db.rollback()
            raise Conflict("only a paused authorization can be resumed")
        row.status, row.pause_reason = "active", None
    elif action == "revoke":
        row.status = "revoked"
    else:  # pragma: no cover  # routes pass fixed values
        raise Unprocessable("UNKNOWN_ACTION")
    row.updated_at, row.version = now, row.version + 1
    management._audit(db, actor, clock, f"release.pilot_{action}d" if action != "pause" else "release.pilot_paused",
                      row.id, {"reason": reason}, target_type="pilot_authorization")  # fmt: skip
    db.commit()
    return row


def authorization_view(row: PilotAuthorization, now: datetime) -> dict[str, Any]:
    return {
        "id": str(row.id), "status": row.status, "pause_reason": row.pause_reason, "purpose": row.purpose,
        "max_per_day": row.max_per_day, "assessment_id": str(row.assessment_id),
        "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(),
        "expired": now >= row.expires_at, "version": row.version,
    }  # fmt: skip


def authorizations(db: Session, org: uuid.UUID) -> list[PilotAuthorization]:
    return list(
        db.scalars(
            select(PilotAuthorization)
            .where(PilotAuthorization.organization_id == org)
            .order_by(PilotAuthorization.created_at.desc())
            .limit(20)
        )
    )


# --- production catalog (read-only) --------------------------------------------------------------------------------


# Tests replace this with a local fake; production builds the pinned Graph client.
def _reader(settings: Settings, connection: Any, now: Any) -> wa.MetaCloudTransport:
    return wa.build_transport(settings, connection, now, purpose="production_read")


def sync_production_catalog(db: Session, *, actor: Actor, clock: Clock, settings: Settings) -> dict[str, Any]:
    """Owner-only GET of Meta's catalog for the production connection. Never a send capability."""
    account_service._require(actor, Capability.ADMINISTER)
    if settings.whatsapp_mode != "production":
        raise Conflict("the production catalog is read only in production mode")
    connection = connections.connection_for(db, actor.organization_id, settings)
    try:
        fetched = _reader(settings, connection, clock.now).list_templates()
    except wa.ProviderCallError as exc:
        raise Conflict(f"Meta refused the catalog read ({exc.error_class})") from None
    now, seen = clock.now(), set()
    for t in fetched:
        seen.add(t.template_id)
        values = {
            "name": t.name, "language": t.language, "category": t.category, "provider_status": t.provider_status,
            "components_digest": t.components_digest, "body_text": t.body_text,
            "body_parameter_count": t.body_parameter_count, "header_parameter_count": t.header_parameter_count,
            "supported": t.supported, "fetched_at": now,
        }  # fmt: skip
        db.execute(
            insert(ProviderTemplate)
            .values(id=uuid.uuid4(), organization_id=actor.organization_id,
                    provider_connection_id=connection.connection_id, template_id=t.template_id, **values)
            .on_conflict_do_update(constraint="uq_provider_templates_template", set_=values)
        )  # fmt: skip
    for row in db.scalars(
        select(ProviderTemplate).where(ProviderTemplate.provider_connection_id == connection.connection_id)
    ):
        if row.template_id not in seen:
            row.provider_status, row.fetched_at = "NOT_RETURNED", now
    management._audit(db, actor, clock, "release.production_catalog_synced", connection.connection_id,
                      {"templates": len(fetched)}, target_type="provider_connection")  # fmt: skip
    db.commit()
    return {"templates": len(fetched)}


def connection_row(db: Session, org: uuid.UUID) -> ProviderConnection | None:
    return db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == org))
