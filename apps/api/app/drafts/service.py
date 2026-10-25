"""Draft Studio service (P4.2, ADR-021): immutable, grounded, reviewable drafts that can never be sent.

Generation locks the campaign and re-checks everything a draft depends on:
- the campaign is open, and the gate is open (live mode) or the campaign is a non-production fixture;
- the account is approved for drafting, not excluded, and the membership is not stale;
- the offer revision is still published with a sales-approved claim;
- the assessment, evidence and rights are current;
- the Asia/Karachi-day drafts budget allows it.

Reads re-check the same conditions and report `blocked_stale` (with reasons) instead of editing the stored
row. Regeneration always appends a new revision.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account, AccountStatus, SourceRecord
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.campaigns import rules as campaign_rules
from app.campaigns import service as campaign_service
from app.campaigns.models import Campaign, CampaignAccount
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound, Unprocessable
from app.drafts import composer
from app.drafts.models import Draft
from app.offers import service as offer_service
from app.offers.models import OfferRevision
from app.qualification import service as qualification
from app.qualification.models import Assessment
from app.signals import rubric as signal_rubric
from app.signals import service as signal_service
from app.signals.models import SchoolSignalSnapshot

NOTICE = "DRAFT ONLY — NOT APPROVED FOR SENDING"


def _membership(db: Session, org: uuid.UUID, campaign_id: uuid.UUID, account_id: uuid.UUID) -> CampaignAccount | None:
    return db.scalar(
        select(CampaignAccount).where(
            CampaignAccount.organization_id == org,
            CampaignAccount.campaign_id == campaign_id,
            CampaignAccount.account_id == account_id,
        )
    )


def _latest_assessment(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> Assessment | None:
    return db.scalar(
        select(Assessment)
        .where(Assessment.organization_id == org, Assessment.account_id == account_id)
        .order_by(Assessment.revision.desc())
        .limit(1)
    )


def blockers(
    db: Session, campaign: Campaign, member: CampaignAccount | None, account: Account, now: datetime, environment: str
) -> list[str]:
    """Everything that forbids a new draft (or makes an existing one stale). Empty = allowed."""
    reasons: list[str] = []
    if account.status == AccountStatus.EXCLUDED:
        reasons.append("account_archived")
    if campaign.status not in ("draft", "active"):
        reasons.append(f"campaign_{campaign.status}")
    gate = campaign_service.gate_blocker(db, campaign, environment, now)
    if gate:
        reasons.append(gate.split(":", 1)[0])
    if member is None:
        reasons.append("not_approved_for_drafting")
    elif member.stage == "excluded":
        reasons.append("excluded")
    else:
        if member.rules_digest != campaign.rules_digest:
            reasons.append("rules_changed")
        if member.offer_revision_id != campaign.offer_revision_id:
            reasons.append("offer_changed")
        head = _latest_assessment(db, campaign.organization_id, account.id)
        if head is None or head.id != member.assessment_id:
            reasons.append("assessment_superseded")
        elif head.input_digest != qualification.current_digest(
            db, campaign.organization_id, account, head.offer_id, now
        ):
            reasons.append("evidence_changed")
    if not campaign_service.offer_is_current(db, campaign):
        reasons.append("offer_not_published")
    return sorted(set(reasons))


def _context(db: Session, campaign: Campaign, account: Account, now: datetime) -> dict[str, Any]:
    org = campaign.organization_id
    facts, _ = signal_service.evidence(db, org, account.id)
    usable = {f.fact_id for f in facts if signal_rubric.eligibility(f, now) == "usable"}
    revision = db.get(OfferRevision, campaign.offer_revision_id)
    claims = []
    if revision is not None:
        content = offer_service.content_of(revision)
        claims = [
            composer.OfferClaim(
                str(campaign.offer_id),
                str(revision.id),
                revision.capability_version,
                revision.content_sha256,
                c.capability_code,
                c.summary,
            )
            for c in content.approved_claims()
        ]
    snapshot = db.scalar(
        select(SchoolSignalSnapshot)
        .where(SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.account_id == account.id)
        .order_by(SchoolSignalSnapshot.created_at.desc(), SchoolSignalSnapshot.id.desc())
        .limit(1)
    )
    questions: list[tuple[str, str]] = []
    if snapshot is not None:
        signals = snapshot.signals_json["signals"]
        questions = [
            (k, signals[k]["question"]) for k in signal_rubric.KEYS if k in signals and signals[k]["state"] == "unknown"
        ]
    return {
        "facts": facts,
        "usable": usable,
        "claims": claims,
        "questions": questions,
        "snapshot_id": str(snapshot.id) if snapshot else None,
    }


def generate(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    campaign_id: uuid.UUID,
    account_id: uuid.UUID,
    template_id: str,
    locale: str,
    idempotency_key: str,
    regenerated_from: uuid.UUID | None = None,
    reason: str | None = None,
    edited_text: str | None = None,
    expected_revision: int | None = None,
) -> tuple[Draft, bool]:
    """Generate a draft, or (with `edited_text`) store an edit as a new revision built only from library sentences."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    request: list[Any] = [str(campaign_id), str(account_id), template_id, locale, str(regenerated_from), reason]
    if edited_text is not None:
        request += [composer.canonical_text(edited_text), expected_revision]
    digest = hashlib.sha256(json.dumps(request).encode()).hexdigest()

    def replay() -> Draft | None:
        prior = db.scalar(select(Draft).where(Draft.organization_id == org, Draft.idempotency_key == idempotency_key))
        if prior is not None and prior.request_digest != digest:
            raise Conflict("idempotency_key was already used with a different draft request")
        return prior

    if (prior := replay()) is not None:
        return prior, False
    campaign = campaign_service._campaign(db, org, campaign_id, lock=True)
    if (prior := replay()) is not None:
        return prior, False
    account = db.scalar(select(Account).where(Account.organization_id == org, Account.id == account_id))
    if account is None:
        raise NotFound()
    member = _membership(db, org, campaign_id, account_id)
    now = clock.now()
    latest = _latest_revision(db, org, campaign_id, account_id)
    if expected_revision is not None and latest != expected_revision:
        raise Conflict("the draft changed since you loaded it; reload the latest revision")
    blocked = blockers(db, campaign, member, account, now, environment)
    if blocked:
        raise Conflict("cannot draft: " + ", ".join(blocked))
    assert member is not None  # noqa: S101  # blockers() refuses a missing membership
    context = _context(db, campaign, account, now)
    try:
        if edited_text is None:
            sentences = composer.compose(
                template_id=template_id,
                locale=locale,
                facts=context["facts"],
                usable=context["usable"],
                claims=context["claims"],
                questions=context["questions"],
                snapshot_id=context["snapshot_id"],
            )
        else:
            sentences = composer.parse(edited_text, composer.candidates(**context))
    except composer.DraftError as exc:
        raise Unprocessable(f"{exc.code}: {'; '.join(exc.details)}") from None
    problems = composer.verify(sentences)
    if problems:
        raise Unprocessable("VALIDATION_FAILED: " + ", ".join(problems))
    if edited_text is None:  # human edits are not generation and do not use the drafts budget
        budgets = campaign_rules.Budgets.model_validate(campaign.budgets_json)
        if not campaign_service.consume_quota(db, campaign, "draft", budgets.drafts_per_day, now):
            raise Conflict("today's draft budget (Asia/Karachi day) is used up")
    fact_ids = sorted({s.grounding["fact_id"] for s in sentences if s.grounding.get("fact_id")})
    cited_sources = [
        uuid.UUID(s.grounding["source_record_id"]) for s in sentences if s.grounding.get("source_record_id")
    ]
    sources = (
        list(
            db.scalars(
                select(SourceRecord.rights_policy_version).where(
                    SourceRecord.organization_id == org, SourceRecord.id.in_(cited_sources)
                )
            )
        )
        if cited_sources
        else []
    )
    head = _latest_assessment(db, org, account_id)
    assert head is not None  # noqa: S101  # blockers() requires the member's assessment to be the latest
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "sentences": composer.to_json(sentences),
                "assessment": [str(head.id), head.revision],
                "offer": str(campaign.offer_revision_id),
                "rules": campaign.rules_digest,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    revision = latest + 1
    draft = Draft(
        organization_id=org,
        campaign_id=campaign_id,
        account_id=account_id,
        membership_id=member.id,
        revision=revision,
        mode=campaign.mode,
        template_id=template_id,
        locale=locale,
        contract_version=composer.CONTRACT_VERSION,
        body_text=composer.render(sentences),
        sentences_json=composer.to_json(sentences),
        assessment_id=head.id,
        assessment_revision=head.revision,
        offer_id=campaign.offer_id,
        offer_revision_id=campaign.offer_revision_id,
        capability_version=campaign.capability_version,
        signal_snapshot_id=uuid.UUID(context["snapshot_id"]) if context["snapshot_id"] else None,
        fact_ids=fact_ids,
        source_policy_versions=sorted(set(sources)),
        fingerprint=fingerprint,
        status="needs_review",
        operator_review_required=True,
        sendable=False,
        channel_eligibility="not_evaluated",
        idempotency_key=idempotency_key,
        request_digest=digest,
        regenerated_from=regenerated_from,
        regenerate_reason=reason,
        origin="generated" if edited_text is None else "edited",
        created_by=actor.user_id,
        created_at=now,
    )
    db.add(draft)
    try:
        db.flush()
        management._audit(
            db,
            actor,
            clock,
            "draft.generated",
            campaign_id,
            {
                "draft_id": str(draft.id),
                "account_id": str(account_id),
                "revision": revision,
                "origin": "generated" if edited_text is None else "edited",
                "content_digest": content_digest(draft),
                "template_id": template_id,
                "mode": campaign.mode,
                "sendable": False,
                "contact_authorized": False,
            },
            target_type="campaign",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if (prior := replay()) is not None:
            return prior, False
        raise Conflict("a draft was created concurrently; reload") from None
    return draft, True


def _latest_revision(db: Session, org: uuid.UUID, campaign_id: uuid.UUID, account_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.max(Draft.revision), 0)).where(
                Draft.organization_id == org, Draft.campaign_id == campaign_id, Draft.account_id == account_id
            )
        )
        or 0
    )


def content_digest(draft: Draft) -> str:
    """SHA-256 of the NFC, whitespace-canonical body: what a reviewer saw and what an approval binds to."""
    return hashlib.sha256(composer.canonical_text(draft.body_text).encode()).hexdigest()


def is_latest(db: Session, draft: Draft) -> bool:
    return _latest_revision(db, draft.organization_id, draft.campaign_id, draft.account_id) == draft.revision


def edit(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    draft_id: uuid.UUID,
    edited_text: str,
    reason: str,
    expected_revision: int,
    idempotency_key: str,
) -> tuple[Draft, bool]:
    """A human edit is a new immutable revision. It may only drop, reorder or swap library sentences."""
    previous = get(db, actor.organization_id, draft_id)
    note = " ".join(reason.split())
    if not 3 <= len(note) <= 500:
        raise Unprocessable("reason must be 3-500 characters")
    if composer.canonical_text(edited_text) == composer.canonical_text(previous.body_text):
        raise Unprocessable("UNCHANGED: the edit is identical to the revision it starts from")
    return generate(
        db,
        actor=actor,
        clock=clock,
        environment=environment,
        campaign_id=previous.campaign_id,
        account_id=previous.account_id,
        template_id=previous.template_id,
        locale=previous.locale,
        idempotency_key=idempotency_key,
        regenerated_from=previous.id,
        reason=note,
        edited_text=edited_text,
        expected_revision=expected_revision,
    )


def regenerate(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    draft_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
    template_id: str | None = None,
) -> tuple[Draft, bool]:
    previous = get(db, actor.organization_id, draft_id)
    note = " ".join(reason.split())
    if not 3 <= len(note) <= 500:
        raise Unprocessable("reason must be 3-500 characters")
    return generate(
        db,
        actor=actor,
        clock=clock,
        environment=environment,
        campaign_id=previous.campaign_id,
        account_id=previous.account_id,
        template_id=template_id or previous.template_id,
        locale=previous.locale,
        idempotency_key=idempotency_key,
        regenerated_from=previous.id,
        reason=note,
    )


def get(db: Session, org: uuid.UUID, draft_id: uuid.UUID) -> Draft:
    draft = db.scalar(select(Draft).where(Draft.organization_id == org, Draft.id == draft_id))
    if draft is None:
        raise NotFound()
    return draft


def view(db: Session, draft: Draft, now: datetime, environment: str) -> dict[str, Any]:
    org = draft.organization_id
    campaign = campaign_service._campaign(db, org, draft.campaign_id)
    account = db.scalar(select(Account).where(Account.organization_id == org, Account.id == draft.account_id))
    assert account is not None  # noqa: S101  # FK-backed
    member = _membership(db, org, draft.campaign_id, draft.account_id)
    reasons = blockers(db, campaign, member, account, now, environment)
    head = _latest_assessment(db, org, draft.account_id)
    if head is None or head.id != draft.assessment_id:
        reasons.append("draft_assessment_superseded")
    if draft.offer_revision_id != campaign.offer_revision_id:
        reasons.append("draft_offer_changed")
    facts, _ = signal_service.evidence(db, org, draft.account_id)
    current = {f.fact_id: f for f in facts}
    for fact_id in draft.fact_ids:
        fact = current.get(fact_id)
        if fact is None:
            reasons.append("cited_fact_corrected")
        elif signal_rubric.eligibility(fact, now) != "usable":
            reasons.append(f"cited_fact_{signal_rubric.eligibility(fact, now)}")
    sources = {
        str(s.id): s
        for s in db.scalars(
            select(SourceRecord).where(
                SourceRecord.organization_id == org,
                SourceRecord.id.in_(
                    [
                        uuid.UUID(s["grounding"]["source_record_id"])
                        for s in draft.sentences_json
                        if s["grounding"].get("source_record_id")
                    ]
                ),
            )
        )
    }
    drilldown = []
    for s in draft.sentences_json:
        entry = {"category": s["category"], "text": s["text"], "grounding": s["grounding"]}
        source = sources.get(str(s["grounding"].get("source_record_id")))
        if source is not None:
            entry["source"] = {
                "provider": source.provider,
                "rights_policy_version": source.rights_policy_version,
                "source_url": source.source_url if source.source_url.startswith("https://") else None,
                "expires_at": source.expires_at.isoformat() if source.expires_at else None,
                "rights_current": source.expires_at is None or source.expires_at > now,
            }
        drilldown.append(entry)
    return {
        "id": str(draft.id),
        "campaign_id": str(draft.campaign_id),
        "account_id": str(draft.account_id),
        "revision": draft.revision,
        "mode": draft.mode,
        "template_id": draft.template_id,
        "locale": draft.locale,
        "contract_version": draft.contract_version,
        "body_text": draft.body_text,
        "sentences": drilldown,
        "status": "blocked_stale" if reasons else draft.status,
        "stale_reasons": sorted(set(reasons)),
        "operator_review_required": True,
        "sendable": False,
        "channel_eligibility": "not_evaluated",
        "notice": NOTICE,
        "offer_revision_id": str(draft.offer_revision_id),
        "capability_version": draft.capability_version,
        "assessment_revision": draft.assessment_revision,
        "regenerated_from": str(draft.regenerated_from) if draft.regenerated_from else None,
        "regenerate_reason": draft.regenerate_reason,
        "origin": draft.origin,
        "content_digest": content_digest(draft),
        "latest": is_latest(db, draft),
        "created_at": draft.created_at.isoformat(),
    }


def list_for(db: Session, org: uuid.UUID, campaign_id: uuid.UUID, account_id: uuid.UUID) -> list[Draft]:
    campaign_service._campaign(db, org, campaign_id)
    return list(
        db.scalars(
            select(Draft)
            .where(Draft.organization_id == org, Draft.campaign_id == campaign_id, Draft.account_id == account_id)
            .order_by(Draft.revision.desc())
        )
    )
