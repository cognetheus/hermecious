"""WhatsApp production readiness (P5.5, ADR-030). Read-only evaluation; it never sends and never grants.

Every check reports `VERIFIED | FAILED | UNKNOWN | BLOCKED_EXTERNAL`, an evidence reference and a reason. Evidence
comes from system records; what the system cannot observe (Meta business verification, Pakistan-local legal
review, a real test receipt on a separate non-production deployment, operations readiness) can only be an owner
attestation with an evidence reference, and it expires. A naked boolean is never accepted.

Status: any FAILED or UNKNOWN -> `no_go`; otherwise any BLOCKED_EXTERNAL -> `blocked_external`; otherwise
`ready_for_operator_review`, which is still not permission to send.

The digest covers only stable evidence (check codes, statuses and evidence references, identity fingerprints,
environment and build), so ordinary traffic does not invalidate a review, but any change in what was reviewed does.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.approvals import service as approvals
from app.approvals.models import DraftReview
from app.contacts.models import ContactPermission
from app.core.settings import Settings
from app.drafts.models import Draft
from app.evaluation import service as evaluation
from app.release.models import ReadinessAttestation
from app.whatsapp.config import production_phone_ids
from app.whatsapp.models import (
    ProviderConnection,
    ProviderEventItem,
    ProviderStatusObservation,
    ProviderTemplate,
    ProviderTestSend,
)

SNAPSHOT_VERSION = "readiness-1.0"
VALIDITY = timedelta(hours=24)
WEBHOOK_HEALTH = timedelta(days=7)
CATALOG_FRESHNESS = timedelta(hours=24)
ATTESTATION_VALIDITY = timedelta(days=90)
TEMPLATE_CATEGORIES = ("MARKETING", "UTILITY")


@dataclass(frozen=True)
class Check:
    code: str
    status: str  # VERIFIED | FAILED | UNKNOWN | BLOCKED_EXTERNAL
    evidence_ref: str | None
    reason: str
    owner: str  # who can resolve it

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "status": self.status, "evidence_ref": self.evidence_ref, "reason": self.reason,
                "owner": self.owner}  # fmt: skip


def _fingerprint(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else None


def _attested(db: Session, org: uuid.UUID, kind: str, now: datetime) -> ReadinessAttestation | None:
    return db.scalar(
        select(ReadinessAttestation)
        .where(ReadinessAttestation.organization_id == org, ReadinessAttestation.kind == kind,
               ReadinessAttestation.expires_at > now)
        .order_by(ReadinessAttestation.attested_at.desc())
        .limit(1)
    )  # fmt: skip


def _attestation_check(db: Session, org: uuid.UUID, kind: str, now: datetime, missing: str, owner: str) -> Check:
    row = _attested(db, org, kind, now)
    if row is None:
        return Check(kind, "BLOCKED_EXTERNAL", None, missing, owner)
    return Check(kind, "VERIFIED", f"attestation:{row.id}", f"owner attestation ({row.evidence_ref[:80]})", owner)


def _connection(db: Session, org: uuid.UUID) -> ProviderConnection | None:
    return db.scalar(select(ProviderConnection).where(ProviderConnection.organization_id == org))


def checks(db: Session, org: uuid.UUID, settings: Settings, now: datetime) -> list[Check]:
    out: list[Check] = []
    connection = _connection(db, org)

    # 1. Provider identity: a bound *production* connection on a configured production phone, credentials present.
    if connection is None or connection.mode != "production":
        out.append(Check("provider_identity", "BLOCKED_EXTERNAL", None,
                         "no WhatsApp connection bound in production mode", "owner"))  # fmt: skip
    elif connection.phone_number_id not in production_phone_ids(settings) or not connection.enabled:
        out.append(Check("provider_identity", "FAILED", f"connection:{connection.id}",
                         "the bound phone is not a configured production phone, or the connection is disabled",
                         "owner"))  # fmt: skip
    elif settings.whatsapp_access_token is None or settings.whatsapp_app_secret is None:
        out.append(Check("provider_identity", "BLOCKED_EXTERNAL", f"connection:{connection.id}",
                         "production access token or app secret is not configured", "owner"))  # fmt: skip
    else:
        out.append(Check("provider_identity", "VERIFIED", f"connection:{connection.id}:v{connection.version}",
                         "production connection bound to the configured WABA and phone", "owner"))  # fmt: skip

    out.append(_attestation_check(db, org, "meta_business_verification", now,
                                  "Meta business verification is not observable here; the owner must attest it",
                                  "owner"))  # fmt: skip

    # 2. A real test message was received (WATEST-10): local signed evidence, or an attestation from the separate
    #    non-production deployment where the P5.3 test ran.
    receipt = db.scalar(
        select(ProviderTestSend.id)
        .join(ProviderStatusObservation, (ProviderStatusObservation.provider_connection_id
                                          == ProviderTestSend.provider_connection_id)
              & (ProviderStatusObservation.provider_message_id == ProviderTestSend.provider_message_id))
        .where(ProviderTestSend.organization_id == org, ProviderTestSend.state == "provider_accepted",
               ProviderTestSend.simulated_transport.is_(False),  # a fake Graph layer is never real evidence
               ProviderStatusObservation.status.in_(("delivered", "read")))
        .order_by(ProviderTestSend.confirmed_at)
        .limit(1)
    )  # fmt: skip
    if receipt is not None:
        out.append(Check("real_test_receipt", "VERIFIED", f"test_send:{receipt}",
                         "a P5.3 test template was delivered, proven by a signed webhook", "owner"))  # fmt: skip
    else:
        out.append(_attestation_check(db, org, "real_test_receipt", now,
                                      "no real test receipt (WATEST-10) is recorded", "owner"))  # fmt: skip

    # 3. Signed callbacks are arriving for this connection.
    if connection is None:
        out.append(Check("webhook_health", "BLOCKED_EXTERNAL", None, "no connection", "owner"))
    else:
        recent = db.scalar(
            select(func.count())
            .select_from(ProviderEventItem)
            .where(
                ProviderEventItem.provider_connection_id == connection.id,
                ProviderEventItem.created_at > now - WEBHOOK_HEALTH,
            )
        )
        out.append(
            Check("webhook_health", "VERIFIED", f"connection:{connection.id}", "signed callbacks received this week",
                  "owner") if recent else
            Check("webhook_health", "BLOCKED_EXTERNAL", None, "no signed callback received in the last 7 days",
                  "owner")
        )  # fmt: skip

    # 4. Meta's catalog has a current approved template of an allowed category.
    templates = []
    if connection is not None:
        templates = sorted(
            db.scalars(
                select(ProviderTemplate.template_id).where(
                    ProviderTemplate.provider_connection_id == connection.id,
                    ProviderTemplate.provider_status == "APPROVED", ProviderTemplate.supported.is_(True),
                    ProviderTemplate.category.in_(TEMPLATE_CATEGORIES),
                    ProviderTemplate.fetched_at > now - CATALOG_FRESHNESS,
                )
            )
        )  # fmt: skip
    out.append(
        Check("template_catalog", "VERIFIED", "templates:" + ",".join(templates),
              f"{len(templates)} approved template(s) fetched from Meta in 24 hours", "owner") if templates else
        Check("template_catalog", "BLOCKED_EXTERNAL", None,
              "no fresh APPROVED marketing/utility template from Meta for this connection", "owner")
    )  # fmt: skip

    # 5. P3.4: the real 30-school evidence audit passed and is current (synthetic samples never count).
    gate = evaluation.gate(db, org, now)
    out.append(
        Check("school_evidence_audit", "VERIFIED", f"evidence_eval:{gate.get('run_id')}", "P3.4 audit passed",
              "operator") if gate["enrollment_allowed"] else
        Check("school_evidence_audit", "FAILED", gate.get("run_id") and f"evidence_eval:{gate['run_id']}",
              f"P3.4 audit gate closed: {gate['reason']}", "operator")
    )  # fmt: skip

    # 6. At least one contact has active, explicit opt-in evidence (P4.3).
    opted_in = db.scalar(
        select(func.count()).select_from(ContactPermission).where(
            ContactPermission.organization_id == org, ContactPermission.status == "verified",
            ContactPermission.expires_at > now,
        )
    )  # fmt: skip
    out.append(
        Check("opt_in_evidence", "VERIFIED", "permissions:present", "explicit opt-in evidence exists", "operator")
        if opted_in else
        Check("opt_in_evidence", "BLOCKED_EXTERNAL", None, "no contact has active explicit opt-in evidence",
              "operator")
    )  # fmt: skip

    # 7. A P4.4 content approval bound to a Meta template is *current now* (each send re-checks its own). P4.4
    #    approves fixture campaigns only today, so in production this stays blocked until the owner decides how
    #    production content is approved (ADR-030 §6).
    approval = current_approval(db, org, settings, now)
    out.append(
        Check("approved_content", "VERIFIED", f"approval:{approval}",
              "a current content approval bound to a Meta template exists", "operator") if approval else
        Check("approved_content", "BLOCKED_EXTERNAL", None,
              "no current P4.4 approval bound to a Meta template (P4.4 has no production approval yet)", "operator")
    )  # fmt: skip

    out.append(Check("operator_inbox", "VERIFIED", "p5.4:inbox", "the read-only operator inbox is deployed (P5.4)",
                     "owner"))  # fmt: skip
    out.append(
        _attestation_check(
            db,
            org,
            "pakistan_legal_review",
            now,
            "Pakistan-local legal review is a human decision; it is not recorded",
            "owner",
        )
    )
    out.append(_attestation_check(db, org, "operations_readiness", now,
                                  "rate/quality monitoring, backups, kill switch and rollback drill not attested",
                                  "owner"))  # fmt: skip
    out.append(
        Check("kill_switch", "FAILED", None, "the global outreach kill switch is engaged", "owner")
        if settings.outreach_kill_switch else
        Check("kill_switch", "VERIFIED", "settings:kill_switch_clear", "the global kill switch is clear", "owner")
    )  # fmt: skip
    out.append(
        Check("deployment_identity", "VERIFIED", f"build:{settings.build_sha}", "the deployed build is identified",
              "owner") if settings.build_sha else
        Check("deployment_identity", "UNKNOWN", None, "HERMECIOUS_BUILD_SHA is not set", "owner")
    )  # fmt: skip
    return out


def current_approval(db: Session, org: uuid.UUID, settings: Settings, now: datetime) -> uuid.UUID | None:
    """The newest P4.4 approval bound to a Meta template that P4.4 itself still reports as current, or None."""
    reviews = db.scalars(
        select(DraftReview)
        .where(DraftReview.organization_id == org, DraftReview.decision == "approved_content",
               DraftReview.template_ref.like("meta:%"))
        .order_by(DraftReview.reviewed_at.desc())
        .limit(20)
    )  # fmt: skip
    for review in reviews:
        draft = db.scalar(select(Draft).where(Draft.organization_id == org, Draft.id == review.draft_id))
        if draft is None:  # pragma: no cover  # composite FK
            continue
        current = approvals.status(db, draft, now, settings)
        if current["state"] == "approved_content" and (current["review"] or {}).get("id") == str(review.id):
            return review.id
    return None


def status_of(results: list[Check]) -> str:
    states = {c.status for c in results}
    if states & {"FAILED", "UNKNOWN"}:
        return "no_go"
    if "BLOCKED_EXTERNAL" in states:
        return "blocked_external"
    return "ready_for_operator_review"


def identity(db: Session, org: uuid.UUID, settings: Settings) -> dict[str, Any]:
    connection = _connection(db, org)
    return {
        "waba": _fingerprint(connection.waba_id if connection else None),
        "phone": _fingerprint(connection.phone_number_id if connection else None),
        "mode": connection.mode if connection else None,
        "connection_version": connection.version if connection else None,
    }


def digest(results: list[Check], ident: dict[str, Any], settings: Settings) -> str:
    stable = {
        "version": SNAPSHOT_VERSION,
        "checks": [(c.code, c.status, c.evidence_ref) for c in results],
        "identity": ident,
        "environment": settings.environment,
        "build": settings.build_sha,
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
