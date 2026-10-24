"""Four-axis assessment and reviewer override (P3.3, ADR-018).

`assess` first refreshes the P3.2 brief, so it reads current evidence. It
then evaluates the pure rubric against that brief, the account's current
facts and the selected offer's *published* revision, and stores a new
revision only when the inputs changed (otherwise it returns the latest).

`override` appends a reviewer revision, which needs `expected_revision`, a
reason and typed changes. It keeps the machine explanation and refuses
anything that contradicts a supported hard disqualifier. Rows are
append-only; reads flag `needs_reassessment` when evidence, rights, offer
or deferral validity has changed since the latest revision.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account, AccountStatus
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.offers import service as offer_service
from app.offers.models import Offer, OfferRevision, OfferStatus, RevisionState
from app.qualification import rubric
from app.qualification.models import Assessment
from app.signals import rubric as signal_rubric
from app.signals import service as signal_service
from app.signals.models import SchoolSignalSnapshot


def _account(db: Session, org: uuid.UUID, account_id: uuid.UUID, *, lock: bool = False) -> Account:
    query = select(Account).where(Account.organization_id == org, Account.id == account_id)
    account = db.scalar(query.with_for_update() if lock else query)
    if account is None:
        raise NotFound()
    return account


def offer_view(db: Session, org: uuid.UUID, account: Account, offer_id: uuid.UUID | None) -> rubric.OfferView | None:
    """The offer as published right now. Without an explicit choice, the single published offer for the vertical."""
    if offer_id is None:
        candidates = list(db.scalars(select(Offer).where(
            Offer.organization_id == org, Offer.vertical_id == account.vertical_id,
            Offer.status == OfferStatus.PUBLISHED)))  # fmt: skip
        if len(candidates) != 1:
            return None
        offer: Offer | None = candidates[0]
    else:
        offer = db.scalar(select(Offer).where(Offer.organization_id == org, Offer.id == offer_id))
        if offer is None:
            raise NotFound()
    assert offer is not None  # noqa: S101  # narrowed above
    revision = db.get(OfferRevision, offer.published_revision_id) if offer.published_revision_id else None
    published = bool(
        offer.status == OfferStatus.PUBLISHED and revision is not None and revision.state == RevisionState.PUBLISHED
    )
    codes: tuple[str, ...] = ()
    if published and revision is not None:
        codes = tuple(sorted(c.capability_code for c in offer_service.content_of(revision).approved_claims()))
    return rubric.OfferView(
        offer_id=str(offer.id), code=offer.code, revision_id=str(revision.id) if revision and published else None,
        capability_version=revision.capability_version if revision and published else None, published=published,
        vertical_matches=offer.vertical_id == account.vertical_id, sellable_capabilities=codes,
    )  # fmt: skip


def _latest(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> Assessment | None:
    return db.scalar(
        select(Assessment)
        .where(Assessment.organization_id == org, Assessment.account_id == account_id)
        .order_by(Assessment.revision.desc())
        .limit(1)
    )


def assess(
    db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID, offer_id: uuid.UUID | None
) -> tuple[Assessment, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    account = _account(db, org, account_id)
    if account.status == AccountStatus.EXCLUDED:
        raise Conflict("archived accounts are not assessed")
    snapshot, _ = signal_service.generate(db, actor=actor, clock=clock, account_id=account_id)
    now = clock.now()
    facts, _links = signal_service.evidence(db, org, account_id)
    offer = offer_view(db, org, account, offer_id)
    result = rubric.assess(facts, snapshot.signals_json["signals"], offer, now)
    digest = rubric.input_digest(snapshot.input_digest, offer, facts, now)
    _account(db, org, account_id, lock=True)  # serializes revision numbering per account
    latest = _latest(db, org, account_id)
    if latest is not None and latest.input_digest == digest:
        db.rollback()
        return latest, False  # nothing changed: the latest revision (machine or reviewer) stands
    dims = result["dimensions"]
    row = Assessment(
        organization_id=org, account_id=account_id, revision=(latest.revision + 1) if latest else 1, origin="rubric",
        rubric_version=rubric.RUBRIC_VERSION, input_digest=digest, signal_snapshot_id=snapshot.id,
        offer_id=uuid.UUID(offer.offer_id) if offer else None,
        offer_revision_id=uuid.UUID(offer.revision_id) if offer and offer.revision_id else None,
        capability_version=offer.capability_version if offer else None,
        customer_fit=dims["customer_fit"]["value"], need_evidence=dims["need_evidence"]["value"],
        accessibility=dims["accessibility"]["value"], delivery_fit=dims["delivery_fit"]["value"],
        decision=result["decision"], channel_eligibility="not_evaluated", explanation_json=result,
        questions_json=result["questions"], supersedes_id=latest.id if latest else None, override_reason=None,
        override_evidence_ids=[], changed_fields=[], created_by=actor.user_id, created_at=now,
    )  # fmt: skip
    db.add(row)
    db.flush()
    management._audit(db, actor, clock, "account.assessed", account_id,
                      {"assessment_id": str(row.id), "revision": row.revision, "decision": row.decision,
                       "rubric_version": rubric.RUBRIC_VERSION})  # fmt: skip
    db.commit()
    return row, True


def override(
    db: Session, *, actor: Actor, clock: Clock, account_id: uuid.UUID, assessment_id: uuid.UUID,
    expected_revision: int, reason: str, decision: str | None, dimensions: dict[str, str],
    evidence_fact_ids: list[uuid.UUID],
) -> Assessment:  # fmt: skip
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    _account(db, org, account_id, lock=True)
    latest = _latest(db, org, account_id)
    if latest is None or latest.id != assessment_id:
        if db.scalar(select(Assessment.id).where(Assessment.organization_id == org, Assessment.id == assessment_id)):
            raise Conflict("only the latest assessment can be overridden; reload")
        raise NotFound()
    if latest.revision != expected_revision:
        raise Conflict("the assessment changed since you loaded it; reload and review again")
    reason = " ".join(reason.split())
    if not 3 <= len(reason) <= 1000:
        raise InvalidRequest("reason must be 3-1000 characters")
    changes: dict[str, str] = {k: v for k, v in dimensions.items() if getattr(latest, k) != v}
    if decision is not None and decision != latest.decision:
        changes["decision"] = decision
    if not changes:
        raise InvalidRequest("an override must change the decision or a dimension")
    now = clock.now()
    facts, _ = signal_service.evidence(db, org, account_id)
    hard = [f for f in facts if f.claim_type == "hard_disqualifier" and signal_rubric.eligibility(f, now) == "usable"]
    if hard and changes.get("decision", latest.decision) != "exclude":
        raise Conflict("a cited hard disqualifier is recorded; this account must stay excluded")
    known = {f.fact_id for f in facts}
    if any(str(i) not in known for i in evidence_fact_ids):
        raise InvalidRequest("evidence must be current facts of this account")
    row = Assessment(
        organization_id=org, account_id=account_id, revision=latest.revision + 1, origin="override",
        rubric_version=latest.rubric_version, input_digest=latest.input_digest,
        signal_snapshot_id=latest.signal_snapshot_id, offer_id=latest.offer_id,
        offer_revision_id=latest.offer_revision_id, capability_version=latest.capability_version,
        customer_fit=changes.get("customer_fit", latest.customer_fit),
        need_evidence=changes.get("need_evidence", latest.need_evidence),
        accessibility=changes.get("accessibility", latest.accessibility),
        delivery_fit=changes.get("delivery_fit", latest.delivery_fit),
        decision=changes.get("decision", latest.decision), channel_eligibility="not_evaluated",
        explanation_json=latest.explanation_json,  # the machine explanation is kept, never rewritten
        questions_json=latest.questions_json, supersedes_id=latest.id, override_reason=reason,
        override_evidence_ids=sorted(str(i) for i in evidence_fact_ids), changed_fields=sorted(changes),
        created_by=actor.user_id, created_at=now,
    )  # fmt: skip
    db.add(row)
    db.flush()
    before = {k: getattr(latest, k) for k in changes}
    management._audit(db, actor, clock, "account.assessment_overridden", account_id,
                      {"assessment_id": str(row.id), "revision": row.revision, "before": before, "after": changes,
                       "reason": reason})  # fmt: skip
    db.commit()
    return row


def view(row: Assessment) -> dict[str, Any]:
    explanation = row.explanation_json
    dims = {
        k: explanation["dimensions"][k]
        | {"value": getattr(row, k), "machine_value": explanation["dimensions"][k]["value"]}
        for k in rubric.DIMENSIONS
    }  # fmt: skip
    return {
        "id": str(row.id), "revision": row.revision, "origin": row.origin, "rubric_version": row.rubric_version,
        "signal_snapshot_id": str(row.signal_snapshot_id), "offer_id": str(row.offer_id) if row.offer_id else None,
        "offer_revision_id": str(row.offer_revision_id) if row.offer_revision_id else None,
        "capability_version": row.capability_version, "dimensions": dims, "decision": row.decision,
        "machine_decision": explanation["decision"],
        "decision_text": rubric.CONTACT_NOW_TEXT if row.decision == "contact_now" else explanation["decision_reason"]
        if row.decision == explanation["decision"] else f"Reviewer decision: {row.decision.replace('_', ' ')}.",
        "machine_reason": explanation["decision_reason"], "blocking": explanation["blocking"],
        "questions": row.questions_json, "channel_eligibility": row.channel_eligibility,
        "override_reason": row.override_reason, "override_evidence_ids": row.override_evidence_ids,
        "changed_fields": row.changed_fields, "created_by": str(row.created_by),
        "created_at": row.created_at.isoformat(),
        "probability": None,  # never a likelihood-to-buy figure
    }  # fmt: skip


def current_digest(db: Session, org: uuid.UUID, account: Account, offer_id: uuid.UUID | None, now: datetime) -> str:
    facts, links = signal_service.evidence(db, org, account.id)
    signal_digest, _ = signal_rubric.input_digest(facts, now, links)
    try:
        offer = offer_view(db, org, account, offer_id)
    except NotFound:
        offer = None
    return rubric.input_digest(signal_digest, offer, facts, now)


def latest(db: Session, org: uuid.UUID, account_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    account = _account(db, org, account_id)
    history = list(db.scalars(
        select(Assessment).where(Assessment.organization_id == org, Assessment.account_id == account_id)
        .order_by(Assessment.revision.desc()).limit(20)))  # fmt: skip
    head = history[0] if history else None
    stale = head is None or head.input_digest != current_digest(db, org, account, head.offer_id, now)
    count = db.scalar(select(func.count()).select_from(SchoolSignalSnapshot).where(
        SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.account_id == account_id))  # fmt: skip
    return {
        "latest": view(head) if head else None,
        "needs_reassessment": stale,
        "history": [{"id": str(a.id), "revision": a.revision, "origin": a.origin, "decision": a.decision,
                     "changed_fields": a.changed_fields, "override_reason": a.override_reason,
                     "created_by": str(a.created_by), "created_at": a.created_at.isoformat()} for a in history],
        "signal_snapshots": int(count or 0),
    }  # fmt: skip
