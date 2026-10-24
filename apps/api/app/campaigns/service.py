"""Campaign planning service (P4.1, ADR-020).

Campaigns, previews and membership decisions are internal planning only:
- nothing here contacts anyone, creates contact permissions or enqueues messages;
- "approved for drafting" means a reviewer may prepare a draft later (P4.2);
- exclusion always wins.

A `live` campaign may approve or activate only while the P3.4 evidence-quality gate is open. A `fixture`
campaign (never in production) may approve synthetic accounts only, clearly labelled test-only.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account, AccountStatus, Vertical
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.campaigns import rules
from app.campaigns.models import Campaign, CampaignAccount, CampaignCommand, CampaignDailyUsage
from app.core.clock import BUSINESS_TZ, Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.evaluation import service as evaluation
from app.offers.models import Offer, OfferRevision, OfferStatus, RevisionState
from app.qualification import service as qualification
from app.qualification.models import Assessment

NO_CONTACT_NOTICE = "Channel permission not checked — do not contact from this screen."
MAX_ACCOUNTS_SCANNED = 500


def _published_revision(db: Session, org: uuid.UUID, offer_id: uuid.UUID) -> tuple[Offer, OfferRevision]:
    offer = db.scalar(select(Offer).where(Offer.organization_id == org, Offer.id == offer_id))
    if offer is None:
        raise NotFound()
    revision = db.get(OfferRevision, offer.published_revision_id) if offer.published_revision_id else None
    if offer.status != OfferStatus.PUBLISHED or revision is None or revision.state != RevisionState.PUBLISHED:
        raise Conflict("the offer is not currently published")
    vertical = db.scalar(select(Vertical.slug).where(Vertical.id == offer.vertical_id))
    if vertical != "schools":
        raise Conflict("the offer is not for the schools vertical")
    return offer, revision


def _campaign(db: Session, org: uuid.UUID, campaign_id: uuid.UUID, *, lock: bool = False) -> Campaign:
    query = select(Campaign).where(Campaign.organization_id == org, Campaign.id == campaign_id)
    campaign = db.scalar(query.with_for_update() if lock else query)
    if campaign is None:
        raise NotFound()
    return campaign


def offer_is_current(db: Session, campaign: Campaign) -> bool:
    offer = db.scalar(
        select(Offer).where(Offer.organization_id == campaign.organization_id, Offer.id == campaign.offer_id)
    )
    return bool(
        offer and offer.status == OfferStatus.PUBLISHED and offer.published_revision_id == campaign.offer_revision_id
    )


def gate_blocker(db: Session, campaign: Campaign, environment: str) -> str | None:
    """Why approvals/activation are blocked by evidence quality or mode (None = allowed)."""
    if campaign.mode == "fixture":
        return "fixture_campaigns_are_test_only_in_production" if environment == "production" else None
    gate = evaluation.gate(db, campaign.organization_id)
    return None if gate["enrollment_allowed"] else f"evidence_quality_gate_closed: {gate['reason']}"


# --- create / update ------------------------------------------------------------------------------------------


def create(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    name: str,
    offer_id: uuid.UUID,
    mode: str,
    district: str | None,
    target: rules.TargetRules,
    budgets: rules.Budgets,
) -> Campaign:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    if mode == "fixture" and environment == "production":
        raise InvalidRequest("fixture campaigns are not allowed in production")
    _offer, revision = _published_revision(db, org, offer_id)
    now = clock.now()
    campaign = Campaign(
        organization_id=org,
        name=" ".join(name.split()),
        vertical_slug="schools",
        city="Lahore",
        district=district,
        mode=mode,
        status="draft",
        offer_id=offer_id,
        offer_revision_id=revision.id,
        capability_version=revision.capability_version,
        rules_json=target.model_dump(mode="json"),
        rules_digest=rules.rules_digest(target),
        rules_version=rules.RULES_VERSION,
        budgets_json=budgets.model_dump(),
        revision=1,
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(campaign)
    db.flush()
    management._audit(
        db,
        actor,
        clock,
        "campaign.created",
        campaign.id,
        {
            "name": campaign.name,
            "mode": mode,
            "offer_revision_id": str(revision.id),
            "rules_digest": campaign.rules_digest,
        },
        target_type="campaign",
    )
    db.commit()
    return campaign


def update(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    campaign_id: uuid.UUID,
    expected_revision: int,
    name: str | None = None,
    target: rules.TargetRules | None = None,
    budgets: rules.Budgets | None = None,
    repin_offer: bool = False,
) -> Campaign:
    account_service._require(actor, Capability.MUTATE)
    campaign = _campaign(db, actor.organization_id, campaign_id, lock=True)
    if campaign.status == "cancelled":
        raise Conflict("cancelled campaigns cannot change")
    if campaign.revision != expected_revision:
        raise Conflict("the campaign changed since you loaded it; reload")
    before = {
        "name": campaign.name,
        "rules_digest": campaign.rules_digest,
        "budgets": campaign.budgets_json,
        "offer_revision_id": str(campaign.offer_revision_id),
    }
    if name is not None:
        campaign.name = " ".join(name.split())
    if target is not None:
        campaign.rules_json, campaign.rules_digest = target.model_dump(mode="json"), rules.rules_digest(target)
    if budgets is not None:
        campaign.budgets_json = budgets.model_dump()
    if repin_offer:
        _offer, revision = _published_revision(db, actor.organization_id, campaign.offer_id)
        campaign.offer_revision_id, campaign.capability_version = revision.id, revision.capability_version
    campaign.revision += 1
    campaign.updated_at = clock.now()
    after = {
        "name": campaign.name,
        "rules_digest": campaign.rules_digest,
        "budgets": campaign.budgets_json,
        "offer_revision_id": str(campaign.offer_revision_id),
    }
    management._audit(
        db,
        actor,
        clock,
        "campaign.updated",
        campaign.id,
        {"before": before, "after": after, "revision": campaign.revision},
        target_type="campaign",
    )
    db.commit()
    return campaign


TRANSITIONS = {
    "activate": ({"draft", "paused"}, "active"),
    "pause": ({"draft", "active"}, "paused"),
    "cancel": ({"draft", "active", "paused"}, "cancelled"),
}


def transition(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    campaign_id: uuid.UUID,
    action: str,
    expected_revision: int,
) -> Campaign:
    account_service._require(actor, Capability.MUTATE)
    campaign = _campaign(db, actor.organization_id, campaign_id, lock=True)
    allowed_from, target = TRANSITIONS[action]
    if campaign.revision != expected_revision:
        raise Conflict("the campaign changed since you loaded it; reload")
    if campaign.status not in allowed_from:
        raise Conflict(f"cannot {action} a {campaign.status} campaign")
    if action == "activate":
        if campaign.mode == "fixture":
            raise Conflict("fixture campaigns stay in draft: they are test-only and never active")
        blocker = gate_blocker(db, campaign, environment)
        if blocker:
            raise Conflict(f"cannot activate: {blocker}")
        if not offer_is_current(db, campaign):
            raise Conflict("cannot activate: the campaign's offer revision is no longer published; re-pin it")
    before = campaign.status
    campaign.status, campaign.revision, campaign.updated_at = target, campaign.revision + 1, clock.now()
    management._audit(
        db,
        actor,
        clock,
        f"campaign.{action}",
        campaign.id,
        {"before": before, "after": target, "revision": campaign.revision},
        target_type="campaign",
    )
    db.commit()
    return campaign


# --- preview ----------------------------------------------------------------------------------------------------


def _candidates(db: Session, campaign: Campaign, now: datetime) -> list[rules.Candidate]:
    org = campaign.organization_id
    accounts = list(
        db.scalars(
            select(Account)
            .join(Vertical, Vertical.id == Account.vertical_id)
            .where(Account.organization_id == org, Vertical.slug == "schools")
            .order_by(Account.id)
            .limit(MAX_ACCOUNTS_SCANNED)
        )
    )
    stages = {
        m.account_id: m.stage
        for m in db.scalars(
            select(CampaignAccount).where(
                CampaignAccount.organization_id == org, CampaignAccount.campaign_id == campaign.id
            )
        )
    }
    out = []
    for account in accounts:
        head = db.scalar(
            select(Assessment)
            .where(Assessment.organization_id == org, Assessment.account_id == account.id)
            .order_by(Assessment.revision.desc())
            .limit(1)
        )
        assessment = None
        if head is not None:
            stale = head.input_digest != qualification.current_digest(db, org, account, head.offer_id, now)
            assessment = {
                "id": str(head.id),
                "revision": head.revision,
                "decision": head.decision,
                "dims": {d: getattr(head, d) for d in rules.DIMENSIONS},
                "offer_revision_id": str(head.offer_revision_id) if head.offer_revision_id else None,
                "needs_reassessment": stale,
            }
        out.append(
            rules.Candidate(
                account_id=str(account.id),
                name=account.canonical_name,
                city=account.city,
                locality=account.locality,
                archived=account.status == AccountStatus.EXCLUDED,
                provenance=evaluation.provenance(db, org, account),
                assessment=assessment,
                manual_stage=stages.get(account.id),
            )
        )
    return out


def preview(
    db: Session,
    *,
    org: uuid.UUID,
    campaign_id: uuid.UUID,
    now: datetime,
    environment: str,
    limit: int,
    cursor: int = 0,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Pure read: never enqueues, allocates contacts or changes membership."""
    campaign = _campaign(db, org, campaign_id)
    target = rules.TargetRules.model_validate(campaign.rules_json)
    budgets = rules.Budgets.model_validate(campaign.budgets_json)
    offer_rev = str(campaign.offer_revision_id)
    rows: list[dict[str, Any]] = []
    for c in _candidates(db, campaign, now):
        result = rules.evaluate(c, target, offer_rev, campaign.mode)
        rows.append(
            {
                "account_id": c.account_id,
                "name": c.name,
                "locality": c.locality,
                "provenance": c.provenance,
                "qualifies": result.qualifies,
                "reasons": result.reasons,
                "decision": c.assessment["decision"] if c.assessment else None,
                "dimensions": c.assessment["dims"] if c.assessment else None,
                "stage": c.manual_stage,
                "item_digest": rules.item_digest(c, campaign.rules_digest, offer_rev),
            }
        )
    rows.sort(key=lambda r: (not r["qualifies"], r["name"].casefold(), r["account_id"]))
    shown = 0
    for row in rows:
        if row["qualifies"]:
            shown += 1
            if shown > budgets.preview_limit:
                row["qualifies"], row["reasons"] = False, ["beyond_preview_limit"]
    digest = hashlib.sha256(json.dumps([r["item_digest"] for r in rows]).encode()).hexdigest()
    if expected_digest is not None and expected_digest != digest:
        raise Conflict("the preview changed; reload it from the start")
    page = rows[cursor : cursor + limit]
    blocker = gate_blocker(db, campaign, environment)
    return {
        "campaign_id": str(campaign.id),
        "revision": campaign.revision,
        "rules_version": campaign.rules_version,
        "preview_digest": digest,
        "total": len(rows),
        "qualifying": min(shown, budgets.preview_limit),
        "items": page,
        "next_cursor": cursor + limit if cursor + limit < len(rows) else None,
        "approval_blocked_reason": blocker or (None if offer_is_current(db, campaign) else "offer_changed"),
        "notice": NO_CONTACT_NOTICE,
        "mode": campaign.mode,
    }


# --- membership ---------------------------------------------------------------------------------------------------


def consume_quota(db: Session, campaign: Campaign, kind: str, limit: int, now: datetime) -> bool:
    """Atomic local-day counter (Asia/Karachi). True if one unit was consumed; False when the budget is spent."""
    day = now.astimezone(BUSINESS_TZ).date()
    db.execute(
        insert(CampaignDailyUsage)
        .values(
            id=uuid.uuid4(),
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            kind=kind,
            day=day,
            used=0,
        )
        .on_conflict_do_nothing(constraint="uq_campaign_usage_day")
    )
    used = db.scalar(
        text(
            "UPDATE campaign_daily_usage SET used = used + 1 WHERE organization_id = :o AND campaign_id = :c"
            " AND kind = :k AND day = :d AND used < :limit RETURNING used"
        ),
        {"o": campaign.organization_id, "c": campaign.id, "k": kind, "d": day, "limit": limit},
    )
    return used is not None


def _replay(db: Session, org: uuid.UUID, key: str, digest: str) -> dict[str, Any] | None:
    prior = db.scalar(
        select(CampaignCommand).where(CampaignCommand.organization_id == org, CampaignCommand.idempotency_key == key)
    )
    if prior is None:
        return None
    if prior.request_digest != digest:
        raise Conflict("idempotency_key was already used with a different request")
    return prior.outcome_json | {"replayed": True}


def _record(db: Session, campaign: Campaign, key: str, digest: str, outcome: dict[str, Any], now: datetime) -> None:
    db.add(
        CampaignCommand(
            organization_id=campaign.organization_id,
            campaign_id=campaign.id,
            idempotency_key=key,
            request_digest=digest,
            outcome_json=outcome,
            created_at=now,
        )
    )


def approve(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    expected_revision: int,
    item_digest: str,
    idempotency_key: str,
    reason: str,
) -> dict[str, Any]:
    """Approve for **drafting review** only. Never a message authorization."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    digest = hashlib.sha256(
        json.dumps(["approve", str(campaign_id), str(account_id), expected_revision, item_digest, reason]).encode()
    ).hexdigest()
    if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
        return replayed
    campaign = _campaign(db, org, campaign_id, lock=True)
    if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
        return replayed  # an identical command committed while we waited for the lock
    if campaign.status not in ("draft", "active"):
        raise Conflict(f"cannot approve while the campaign is {campaign.status}")
    if campaign.revision != expected_revision:
        raise Conflict("the campaign changed since you loaded it; reload the preview")
    blocker = gate_blocker(db, campaign, environment)
    if blocker:
        raise Conflict(f"cannot approve: {blocker}")
    if not offer_is_current(db, campaign):
        raise Conflict("cannot approve: the campaign's offer revision is no longer published")
    now = clock.now()
    existing = db.scalar(
        select(CampaignAccount)
        .where(
            CampaignAccount.organization_id == org,
            CampaignAccount.campaign_id == campaign.id,
            CampaignAccount.account_id == account_id,
        )
        .with_for_update()
    )
    if existing is not None and existing.stage == "excluded":
        raise Conflict("this account is excluded from the campaign; exclusion wins")
    if existing is not None:  # already approved (e.g. by a concurrent reviewer): converge, consume nothing
        outcome = {"account_id": str(account_id), "stage": existing.stage, "converged": True}
        _record(db, campaign, idempotency_key, digest, outcome, now)
        db.commit()
        return outcome | {"replayed": False}
    candidate = next((c for c in _candidates(db, campaign, now) if c.account_id == str(account_id)), None)
    if candidate is None:
        raise NotFound()
    target = rules.TargetRules.model_validate(campaign.rules_json)
    offer_rev = str(campaign.offer_revision_id)
    if rules.item_digest(candidate, campaign.rules_digest, offer_rev) != item_digest:
        raise Conflict("the preview is stale for this account; reload it")
    result = rules.evaluate(candidate, target, offer_rev, campaign.mode)
    if not result.qualifies:
        raise Conflict("not a qualifying candidate: " + ", ".join(result.reasons))
    budgets = rules.Budgets.model_validate(campaign.budgets_json)
    if not consume_quota(db, campaign, "approval", budgets.approvals_per_day, now):
        raise Conflict("today's approval budget (Asia/Karachi day) is used up")
    assert candidate.assessment is not None  # noqa: S101  # qualifying candidates are assessed
    member = CampaignAccount(
        organization_id=org,
        campaign_id=campaign.id,
        account_id=account_id,
        stage="approved_for_drafting",
        assessment_id=uuid.UUID(candidate.assessment["id"]),
        assessment_revision=candidate.assessment["revision"],
        offer_revision_id=campaign.offer_revision_id,
        rules_digest=campaign.rules_digest,
        item_digest=item_digest,
        reason=" ".join(reason.split())[:500],
        version=1,
        decided_by=actor.user_id,
        decided_at=now,
    )
    db.add(member)
    outcome = {"account_id": str(account_id), "stage": "approved_for_drafting", "converged": False}
    _record(db, campaign, idempotency_key, digest, outcome, now)
    management._audit(
        db,
        actor,
        clock,
        "campaign.candidate_approved",
        campaign.id,
        {
            "account_id": str(account_id),
            "assessment_id": candidate.assessment["id"],
            "mode": campaign.mode,
            "contact_authorized": False,
        },
        target_type="campaign",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
            return replayed
        raise Conflict("this candidate was decided concurrently; reload") from None
    return outcome | {"replayed": False}


def exclude(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Exclusion always wins over approvals and any later planned work."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    digest = hashlib.sha256(json.dumps(["exclude", str(campaign_id), str(account_id), reason]).encode()).hexdigest()
    if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
        return replayed
    campaign = _campaign(db, org, campaign_id, lock=True)
    if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
        return replayed
    if db.scalar(select(Account.id).where(Account.organization_id == org, Account.id == account_id)) is None:
        raise NotFound()
    now = clock.now()
    note = " ".join(reason.split())
    if not 3 <= len(note) <= 500:
        raise InvalidRequest("reason must be 3-500 characters")
    existing = db.scalar(
        select(CampaignAccount)
        .where(
            CampaignAccount.organization_id == org,
            CampaignAccount.campaign_id == campaign.id,
            CampaignAccount.account_id == account_id,
        )
        .with_for_update()
    )
    before = existing.stage if existing else None
    if existing is None:
        db.add(
            CampaignAccount(
                organization_id=org,
                campaign_id=campaign.id,
                account_id=account_id,
                stage="excluded",
                offer_revision_id=campaign.offer_revision_id,
                rules_digest=campaign.rules_digest,
                reason=note,
                version=1,
                decided_by=actor.user_id,
                decided_at=now,
            )
        )
    elif existing.stage != "excluded":
        existing.stage, existing.reason, existing.version = "excluded", note, existing.version + 1
        existing.decided_by, existing.decided_at = actor.user_id, now
    outcome = {"account_id": str(account_id), "stage": "excluded", "previous_stage": before}
    _record(db, campaign, idempotency_key, digest, outcome, now)
    management._audit(
        db,
        actor,
        clock,
        "campaign.candidate_excluded",
        campaign.id,
        {"account_id": str(account_id), "before": before, "reason": note},
        target_type="campaign",
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if (replayed := _replay(db, org, idempotency_key, digest)) is not None:
            return replayed
        raise Conflict("this candidate was decided concurrently; reload") from None
    return outcome | {"replayed": False}


# --- read models --------------------------------------------------------------------------------------------------


def view(db: Session, campaign: Campaign, now: datetime, environment: str) -> dict[str, Any]:
    org = campaign.organization_id
    members = list(
        db.scalars(
            select(CampaignAccount)
            .where(CampaignAccount.organization_id == org, CampaignAccount.campaign_id == campaign.id)
            .order_by(CampaignAccount.decided_at)
        )
    )
    names = (
        {
            a.id: (a.canonical_name, a)
            for a in db.scalars(
                select(Account).where(Account.organization_id == org, Account.id.in_([m.account_id for m in members]))
            )
        }
        if members
        else {}
    )
    out_members = []
    for m in members:
        stale: list[str] = []
        if m.stage == "approved_for_drafting":
            if m.rules_digest != campaign.rules_digest:
                stale.append("rules_changed")
            if m.offer_revision_id != campaign.offer_revision_id or not offer_is_current(db, campaign):
                stale.append("offer_changed")
            head = db.scalar(
                select(Assessment)
                .where(Assessment.organization_id == org, Assessment.account_id == m.account_id)
                .order_by(Assessment.revision.desc())
                .limit(1)
            )
            account = names.get(m.account_id, (None, None))[1]
            if head is None or head.id != m.assessment_id:
                stale.append("assessment_superseded")
            elif account is not None and head.input_digest != qualification.current_digest(
                db, org, account, head.offer_id, now
            ):
                stale.append("evidence_changed")
        out_members.append(
            {
                "account_id": str(m.account_id),
                "name": names.get(m.account_id, ("?", None))[0],
                "stage": m.stage,
                "reason": m.reason,
                "version": m.version,
                "decided_at": m.decided_at.isoformat(),
                "stale": stale,
                "drafting_blocked": m.stage != "approved_for_drafting" or bool(stale),
            }
        )
    usage = {
        f"{u.kind}:{u.day.isoformat()}": u.used
        for u in db.scalars(
            select(CampaignDailyUsage).where(
                CampaignDailyUsage.organization_id == org, CampaignDailyUsage.campaign_id == campaign.id
            )
        )
    }
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": campaign.status,
        "mode": campaign.mode,
        "revision": campaign.revision,
        "city": campaign.city,
        "district": campaign.district,
        "vertical_slug": campaign.vertical_slug,
        "offer_id": str(campaign.offer_id),
        "offer_revision_id": str(campaign.offer_revision_id),
        "capability_version": campaign.capability_version,
        "offer_current": offer_is_current(db, campaign),
        "rules": campaign.rules_json,
        "rules_version": campaign.rules_version,
        "rules_digest": campaign.rules_digest,
        "budgets": campaign.budgets_json,
        "usage": usage,
        "members": out_members,
        "approval_blocked_reason": gate_blocker(db, campaign, environment),
        "notice": NO_CONTACT_NOTICE,
        "contact_authorized": False,
        "created_at": campaign.created_at.isoformat(),
        "updated_at": campaign.updated_at.isoformat(),
    }
