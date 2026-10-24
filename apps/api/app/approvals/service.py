"""Approval Studio (P4.4, ADR-023): content approval of one exact draft revision. Simulation only.

- **Approve content only** binds:
  - the exact revision by content digest, the contact, the business identity, the purpose and a template;
  - a version vector (campaign, rules, offer, assessment, evidence, policy and permission).
  Before writing, it re-checks P4.2 staleness and grounding, the P4.3 eligibility decision and the campaign mode.
  Only fixture campaigns can be approved, and every receipt is `simulation_only`.
- **Rejection and revocation** append receipts; nothing is overwritten.
- **Status is computed on read** from the latest receipt plus live dependencies, so a stale approval reads as
  `approval_stale`. Replays, restarts and older revisions never restore an approval.
- Approval is not consent, not a queue entry, not a WhatsApp template approval and not a send authorization.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account
from app.approvals.models import DraftReview
from app.auth.dependencies import Capability
from app.auth.models import User
from app.auth.service import Actor
from app.campaigns import service as campaign_service
from app.campaigns.models import Campaign
from app.contacts import service as contacts
from app.core.clock import Clock
from app.core.errors import Conflict, Unprocessable
from app.core.settings import Settings
from app.drafts import composer
from app.drafts import service as drafts
from app.drafts.models import Draft
from app.eligibility import policy
from app.eligibility import service as eligibility

APPROVAL_TTL = timedelta(days=7)
PURPOSE: policy.Purpose = "marketing"  # a first-contact draft is business-initiated
NOTICE = "Content approval only — simulation only. Not queued, not sent, not a WhatsApp template approval."


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _replay(db: Session, org: uuid.UUID, key: str, digest: str) -> DraftReview | None:
    prior = db.scalar(select(DraftReview).where(DraftReview.organization_id == org, DraftReview.idempotency_key == key))
    if prior is not None and prior.request_digest != digest:
        raise Conflict("idempotency_key was already used with a different review request")
    return prior


def _latest(db: Session, draft: Draft) -> DraftReview | None:
    return db.scalar(
        select(DraftReview)
        .where(DraftReview.organization_id == draft.organization_id, DraftReview.draft_id == draft.id)
        .order_by(DraftReview.seq.desc())
        .limit(1)
    )


def _context(db: Session, draft: Draft) -> tuple[Campaign, Account]:
    campaign = campaign_service._campaign(db, draft.organization_id, draft.campaign_id)
    account = db.scalar(
        select(Account).where(Account.organization_id == draft.organization_id, Account.id == draft.account_id)
    )
    assert account is not None  # noqa: S101  # FK-backed
    return campaign, account


def _grounding_problems(db: Session, draft: Draft, campaign: Campaign, account: Account, now: datetime) -> list[str]:
    """Re-run the P4.2 verifier and require every sentence to still be in the current library, exactly."""
    sentences = [composer.Sentence(s["category"], s["text"], s["grounding"]) for s in draft.sentences_json]
    problems = [f"verifier_{p}" for p in composer.verify(sentences)]
    library = composer.candidates(**drafts._context(db, campaign, account, now))
    allowed = {(s.category, s.text, json.dumps(s.grounding, sort_keys=True)) for s in library}
    for s in sentences:
        if (s.category, s.text, json.dumps(s.grounding, sort_keys=True)) not in allowed:
            problems.append(f"grounding_changed_{s.category}")
    return problems


def dependencies(db: Session, draft: Draft, now: datetime, environment: str) -> list[str]:
    """Why this revision cannot be (or no longer is) content-approvable. Empty = approvable."""
    campaign, account = _context(db, draft)
    reasons = list(drafts.view(db, draft, now, environment)["stale_reasons"])
    if not drafts.is_latest(db, draft):
        reasons.append("newer_revision_exists")
    if campaign.mode != "fixture":
        reasons.append("production_approval_unavailable")
    reasons += _grounding_problems(db, draft, campaign, account, now)
    return sorted(set(reasons))


def _vector(
    draft: Draft, campaign: Campaign, decision: dict[str, Any], contact_id: uuid.UUID, template_ref: str
) -> dict[str, Any]:
    return {
        "draft_id": str(draft.id),
        "draft_revision": draft.revision,
        "content_digest": drafts.content_digest(draft),
        "campaign_id": str(campaign.id),
        "campaign_revision": campaign.revision,
        "campaign_mode": campaign.mode,
        "rules_digest": campaign.rules_digest,
        "offer_revision_id": str(draft.offer_revision_id),
        "capability_version": draft.capability_version,
        "assessment_id": str(draft.assessment_id),
        "assessment_revision": draft.assessment_revision,
        "fact_ids": list(draft.fact_ids),
        "source_policy_versions": list(draft.source_policy_versions),
        "business": composer.SENDER["organization"],
        "contact_id": str(contact_id),
        "purpose": PURPOSE,
        "template_ref": template_ref,
        "policy_version": decision["policy_version"],
        "permission_revision": decision["permission_revision"],
        "suppression_revision": decision["suppression_revision"],
        "eligibility_decision": decision["decision"],
        "eligibility_reasons": [r["code"] for r in decision["reasons"]],
    }


def _decide(
    db: Session, draft: Draft, contact_id: uuid.UUID, template_ref: str, now: datetime, settings: Settings
) -> dict[str, Any]:
    return eligibility.decide(
        db,
        org=draft.organization_id,
        now=now,
        settings=settings,
        contact_id=contact_id,
        purpose=PURPOSE,
        campaign_id=draft.campaign_id,
        template_ref=template_ref,
        inbound_ref=None,
    )


def _commit(db: Session, org: uuid.UUID, key: str, digest: str, row: DraftReview) -> tuple[DraftReview, bool]:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if (prior := _replay(db, org, key, digest)) is not None:
            return prior, False
        raise Conflict("another reviewer decided this revision at the same moment; reload") from None
    return row, True


def _start(
    db: Session, actor: Actor, draft_id: uuid.UUID, key: str, digest: str
) -> tuple[DraftReview | None, Draft | None]:
    """Replay check, then lock the campaign (serialises reviews) and re-check the replay."""
    org = actor.organization_id
    if (prior := _replay(db, org, key, digest)) is not None:
        return prior, None
    draft = drafts.get(db, org, draft_id)
    campaign_service._campaign(db, org, draft.campaign_id, lock=True)
    if (prior := _replay(db, org, key, digest)) is not None:
        return prior, None
    return None, draft


def _clean(reason: str) -> str:
    note = " ".join(reason.split())
    if not 3 <= len(note) <= 500:
        raise Unprocessable("reason must be 3-500 characters")
    return note


def approve(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    settings: Settings,
    draft_id: uuid.UUID,
    content_digest: str,
    contact_id: uuid.UUID | None,
    template_ref: str | None,
    reason: str,
    idempotency_key: str,
) -> tuple[DraftReview, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    note = _clean(reason)
    digest = _digest("approve", str(draft_id), content_digest, str(contact_id), template_ref, note)
    prior, draft = _start(db, actor, draft_id, idempotency_key, digest)
    if prior is not None:
        return prior, False
    assert draft is not None  # noqa: S101
    if contact_id is None:
        raise Unprocessable("NO_CONTACT_SELECTED: choose the contact this content is for (the draft stays editable)")
    if template_ref is None:
        raise Unprocessable("NO_TEMPLATE_SELECTED: business-initiated content needs a template reference")
    if content_digest != drafts.content_digest(draft):
        raise Conflict("the content digest does not match this revision; reload what you reviewed")
    now = clock.now()
    blocked = dependencies(db, draft, now, settings.environment)
    if blocked:
        raise Conflict("cannot approve: " + ", ".join(blocked))
    contact = contacts.get(db, org, contact_id)
    if contact.account_id != draft.account_id:
        raise Unprocessable("CONTACT_NOT_FOR_ACCOUNT: the contact belongs to a different account")
    decision = _decide(db, draft, contact_id, template_ref, now, settings)
    if decision["decision"] == "deny":
        raise Conflict("not simulation-eligible: " + ", ".join(r["code"] for r in decision["reasons"]))
    latest = _latest(db, draft)
    if latest is not None and latest.decision == "approved_content":
        raise Conflict("this revision already has a content approval; revoke it before approving again")
    if latest is not None and latest.decision == "rejected":
        raise Conflict("this revision was rejected; edit or regenerate to create a new revision")
    campaign, _account = _context(db, draft)
    row = DraftReview(
        organization_id=org,
        draft_id=draft.id,
        campaign_id=draft.campaign_id,
        account_id=draft.account_id,
        draft_revision=draft.revision,
        seq=(latest.seq if latest else 0) + 1,
        decision="approved_content",
        content_digest=content_digest,
        contact_id=contact_id,
        purpose=PURPOSE,
        template_ref=template_ref,
        eligibility_decision=decision["decision"],
        simulation_only=True,
        version_vector=_vector(draft, campaign, decision, contact_id, template_ref),
        reason=note,
        reviewer_id=actor.user_id,
        reviewed_at=now,
        expires_at=now + APPROVAL_TTL,
        idempotency_key=idempotency_key,
        request_digest=digest,
    )
    db.add(row)
    management._audit(
        db,
        actor,
        clock,
        "draft.content_approved",
        draft.campaign_id,
        {
            "draft_id": str(draft.id),
            "revision": draft.revision,
            "content_digest": content_digest,
            "contact_id": str(contact_id),
            "eligibility_decision": decision["decision"],
            "simulation_only": True,
            "live_send_authorized": False,
        },
        target_type="campaign",
    )
    return _commit(db, org, idempotency_key, digest, row)


def reject(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    draft_id: uuid.UUID,
    content_digest: str,
    reason: str,
    idempotency_key: str,
) -> tuple[DraftReview, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    note = _clean(reason)
    digest = _digest("reject", str(draft_id), content_digest, note)
    prior, draft = _start(db, actor, draft_id, idempotency_key, digest)
    if prior is not None:
        return prior, False
    assert draft is not None  # noqa: S101
    if content_digest != drafts.content_digest(draft):
        raise Conflict("the content digest does not match this revision; reload what you reviewed")
    latest = _latest(db, draft)
    if latest is not None and latest.decision == "approved_content":
        raise Conflict("revoke the current approval before rejecting this revision")
    if latest is not None and latest.decision == "rejected":
        raise Conflict("this revision is already rejected")
    now = clock.now()
    row = DraftReview(
        organization_id=org,
        draft_id=draft.id,
        campaign_id=draft.campaign_id,
        account_id=draft.account_id,
        draft_revision=draft.revision,
        seq=(latest.seq if latest else 0) + 1,
        decision="rejected",
        content_digest=content_digest,
        simulation_only=True,
        version_vector={"draft_id": str(draft.id), "draft_revision": draft.revision, "content_digest": content_digest},
        reason=note,
        reviewer_id=actor.user_id,
        reviewed_at=now,
        idempotency_key=idempotency_key,
        request_digest=digest,
    )
    db.add(row)
    management._audit(
        db,
        actor,
        clock,
        "draft.content_rejected",
        draft.campaign_id,
        {"draft_id": str(draft.id), "revision": draft.revision, "content_digest": content_digest},
        target_type="campaign",
    )
    return _commit(db, org, idempotency_key, digest, row)


def revoke(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    draft_id: uuid.UUID,
    approval_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
) -> tuple[DraftReview, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    note = _clean(reason)
    digest = _digest("revoke", str(draft_id), str(approval_id), note)
    prior, draft = _start(db, actor, draft_id, idempotency_key, digest)
    if prior is not None:
        return prior, False
    assert draft is not None  # noqa: S101
    latest = _latest(db, draft)
    if latest is None or latest.id != approval_id or latest.decision != "approved_content":
        raise Conflict("only the current approval of this revision can be revoked; reload")
    now = clock.now()
    row = DraftReview(
        organization_id=org,
        draft_id=draft.id,
        campaign_id=draft.campaign_id,
        account_id=draft.account_id,
        draft_revision=draft.revision,
        seq=latest.seq + 1,
        decision="revoked",
        content_digest=latest.content_digest,
        simulation_only=True,
        version_vector={"revokes": str(latest.id), "draft_revision": draft.revision},
        reason=note,
        reviewer_id=actor.user_id,
        reviewed_at=now,
        revokes_id=latest.id,
        idempotency_key=idempotency_key,
        request_digest=digest,
    )
    db.add(row)
    management._audit(
        db,
        actor,
        clock,
        "draft.content_approval_revoked",
        draft.campaign_id,
        {"draft_id": str(draft.id), "approval_id": str(latest.id), "reason": note},
        target_type="campaign",
    )
    return _commit(db, org, idempotency_key, digest, row)


# --- reads ---------------------------------------------------------------------------------------------------


def receipt(db: Session, review: DraftReview) -> dict[str, Any]:
    reviewer = db.execute(
        select(User.display_name, User.email_canonical).where(
            User.organization_id == review.organization_id, User.id == review.reviewer_id
        )
    ).first()
    return {
        "id": str(review.id),
        "seq": review.seq,
        "decision": review.decision,
        "draft_id": str(review.draft_id),
        "draft_revision": review.draft_revision,
        "content_digest": review.content_digest,
        "contact_id": str(review.contact_id) if review.contact_id else None,
        "purpose": review.purpose,
        "template_ref": review.template_ref,
        "eligibility_decision": review.eligibility_decision,
        "reason": review.reason,
        "reviewer": (reviewer[0] or reviewer[1]) if reviewer else None,
        "reviewed_at": review.reviewed_at.isoformat(),
        "expires_at": review.expires_at.isoformat() if review.expires_at else None,
        "revokes_id": str(review.revokes_id) if review.revokes_id else None,
        "simulation_only": True,
        "version_vector": review.version_vector,
    }


def status(db: Session, draft: Draft, now: datetime, settings: Settings) -> dict[str, Any]:
    """Computed from the latest receipt and live dependencies; a stored approval alone proves nothing."""
    latest = _latest(db, draft)
    base: dict[str, Any] = {
        "simulation_only": True,
        "queued": False,
        "sent": False,
        "whatsapp_template_approved": False,
        "production_ready": False,
        "notice": NOTICE,
        "stale_reasons": [],
        "review": receipt(db, latest) if latest is not None else None,
    }
    if latest is None:
        return base | {"state": "not_reviewed"}
    if latest.decision != "approved_content":
        return base | {"state": latest.decision}
    assert latest.contact_id is not None and latest.template_ref is not None  # noqa: S101  # DB check
    reasons = dependencies(db, draft, now, settings.environment)
    if latest.expires_at is not None and now >= latest.expires_at:
        reasons.append("approval_expired")
    if drafts.content_digest(draft) != latest.content_digest:
        reasons.append("content_changed")  # pragma: no cover  # drafts are immutable
    decision = _decide(db, draft, latest.contact_id, latest.template_ref, now, settings)
    if decision["decision"] == "deny":
        reasons += [f"eligibility_{r['code']}" for r in decision["reasons"]]
    if decision["permission_revision"] != latest.version_vector.get("permission_revision"):
        reasons.append("permission_changed")
    campaign, _account = _context(db, draft)
    if campaign.revision != latest.version_vector.get("campaign_revision"):
        reasons.append("campaign_changed")
    reasons = sorted(set(reasons))
    return base | {"state": "approval_stale" if reasons else "approved_content", "stale_reasons": reasons}


def history(db: Session, draft: Draft) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DraftReview)
        .where(DraftReview.organization_id == draft.organization_id, DraftReview.draft_id == draft.id)
        .order_by(DraftReview.seq.desc())
    )
    return [receipt(db, r) for r in rows]
