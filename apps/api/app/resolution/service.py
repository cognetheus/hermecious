"""Campus identity resolution service (P2.3, ADR-014).

`run_resolution` proposes pairs (blocked by city + name token), runs the pure
matcher and stores only `suggest_review` / `insufficient_evidence` outcomes as
pending suggestions. It never merges and never rewrites a reviewed decision.

`decide` applies one human review command:
- idempotent per `command_id`;
- 409 on a stale version or a reused command id with a different payload;
- every decision is appended to `identity_decisions`.

Confirming a candidate↔account pair creates a link. Undo ends that link only
when no current fact on the account cites the candidate's source and was
recorded after linking. Otherwise the suggestion moves to
`reallocation_review` and the facts are listed, never silently moved.
"""

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.accounts import management, policy
from app.accounts import service as account_service
from app.accounts.models import Account, AccountAlias, AccountFact, AccountStatus
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.core.request_context import current_request_id
from app.discovery.models import DiscoveryCandidate
from app.resolution import matcher
from app.resolution.models import CandidateAccountLink, IdentityDecision, IdentitySuggestion

Action = Literal["confirm_same_campus", "mark_distinct", "defer", "undo"]
STORED = ("suggest_review", "insufficient_evidence")
OPEN = ("pending", "deferred", "undone")
TRANSITIONS: dict[str, dict[str, str]] = {
    "confirm_same_campus": {s: "confirmed" for s in OPEN},
    "mark_distinct": {s: "distinct" for s in OPEN},
    "defer": {"pending": "deferred", "undone": "deferred"},
    "undo": {"confirmed": "undone", "distinct": "undone", "deferred": "undone", "reallocation_review": "undone"},
}


@dataclass
class ResolutionReport:
    algorithm_version: str
    candidates: int
    accounts: int
    pairs_considered: int
    skipped_common_blocks: int
    outcomes: dict[str, int]
    created: int = 0
    recomputed: int = 0
    superseded: int = 0
    unchanged: int = 0
    evidence_changed_on_reviewed: int = 0


@dataclass
class DecisionResult:
    suggestion: IdentitySuggestion
    decision_id: uuid.UUID
    replayed: bool
    held_fact_ids: list[str] = field(default_factory=list)
    link_id: uuid.UUID | None = None


def _candidate_side(row: DiscoveryCandidate) -> matcher.Side:
    names = tuple(n for n in (row.display_name, row.name_local) if n)
    precision = row.location_precision if row.location_precision in ("point", "area_center") else None
    return matcher.Side(
        ref=f"c:{row.id}",
        provider=row.provider,
        external_key=row.external_key,
        names=names,
        city=row.city,
        locality=row.locality,
        latitude=float(row.latitude) if row.latitude is not None else None,
        longitude=float(row.longitude) if row.longitude is not None else None,
        precision=precision,  # type: ignore[arg-type]
    )


def _account_side(row: Account, aliases: list[str]) -> matcher.Side:
    return matcher.Side(
        ref=f"a:{row.id}", provider=None, external_key=None, names=(row.canonical_name, *aliases), city=row.city,
        locality=row.locality,
    )  # fmt: skip


def run_resolution(db: Session, *, actor: Actor, clock: Clock) -> ResolutionReport:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    now = clock.now()
    candidates = {
        c.id: c
        for c in db.scalars(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.organization_id == org, DiscoveryCandidate.status != "rejected"
            )
        )
    }
    accounts = {
        a.id: a
        for a in db.scalars(
            select(Account).where(Account.organization_id == org, Account.status != AccountStatus.EXCLUDED)
        )
    }
    aliases: dict[uuid.UUID, list[str]] = {}
    for alias in db.scalars(select(AccountAlias).where(AccountAlias.organization_id == org)):
        aliases.setdefault(alias.account_id, []).append(alias.normalized_name)
    linked = {
        (link.candidate_id, link.account_id)
        for link in db.scalars(
            select(CandidateAccountLink).where(
                CandidateAccountLink.organization_id == org, CandidateAccountLink.unlinked_at.is_(None)
            )
        )
    }
    sides = [_candidate_side(c) for c in candidates.values()]
    sides += [_account_side(a, aliases.get(a.id, [])) for a in accounts.values()]
    pairs, skipped = matcher.candidate_pairs(sides)

    outcomes: Counter[str] = Counter()
    report = ResolutionReport(matcher.ALGORITHM_VERSION, len(candidates), len(accounts), 0, skipped, {})
    for left, right in pairs:
        kinds = (left.ref[0], right.ref[0])
        if kinds == ("a", "a"):
            continue  # account de-duplication is not P2.3 scope
        if kinds == ("a", "c"):
            left, right = right, left
        left_id = uuid.UUID(left.ref[2:])
        right_id = uuid.UUID(right.ref[2:])
        if right.ref[0] == "a" and (left_id, right_id) in linked:
            continue
        report.pairs_considered += 1
        match = matcher.compare(left, right)
        outcomes[match.resolution] += 1
        if right.ref[0] == "c" and right_id < left_id:
            left_id, right_id = right_id, left_id
        _store(db, org, now, candidates, left_id, right_id if right.ref[0] == "c" else None,
               right_id if right.ref[0] == "a" else None, match, report)  # fmt: skip
    report.outcomes = dict(sorted(outcomes.items()))
    management._audit(
        db,
        actor,
        clock,
        "identity.resolution_run",
        uuid.uuid4(),
        {k: v for k, v in report.__dict__.items() if k != "outcomes"} | {"outcomes": report.outcomes},
        target_type="identity_run",
    )
    db.commit()
    return report


def _store(
    db: Session,
    org: uuid.UUID,
    now: datetime,
    candidates: dict[uuid.UUID, DiscoveryCandidate],
    left_id: uuid.UUID,
    right_candidate_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    match: matcher.Match,
    report: ResolutionReport,
) -> None:
    left, right = candidates[left_id], candidates.get(right_candidate_id) if right_candidate_id else None
    evidence = sorted(str(c.source_record_id) for c in (left, right) if c is not None and c.source_record_id)
    pair_filter = and_(
        IdentitySuggestion.organization_id == org,
        IdentitySuggestion.left_candidate_id == left_id,
        IdentitySuggestion.algorithm_version == match.algorithm_version,
        IdentitySuggestion.right_candidate_id == right_candidate_id
        if right_candidate_id
        else IdentitySuggestion.existing_account_id == account_id,
    )
    existing = db.scalar(select(IdentitySuggestion).where(pair_filter).with_for_update())
    revisions = (left.revision, right.revision if right else None)
    if existing is None:
        if match.resolution not in STORED:
            return
        db.execute(
            insert(IdentitySuggestion)
            .values(
                id=uuid.uuid4(),
                organization_id=org,
                left_candidate_id=left_id,
                right_candidate_id=right_candidate_id,
                existing_account_id=account_id,
                algorithm_version=match.algorithm_version,
                resolution=match.resolution,
                reason_codes=list(match.reason_codes),
                features=match.features,
                evidence_source_record_ids=evidence,
                left_revision=revisions[0],
                right_revision=revisions[1],
                status="pending",
                version=1,
                created_at=now,
                updated_at=now,
            )  # fmt: skip
            .on_conflict_do_nothing(
                index_elements=[
                    "organization_id",
                    "left_candidate_id",
                    "right_candidate_id" if right_candidate_id else "existing_account_id",
                    "algorithm_version",
                ],
                index_where=IdentitySuggestion.right_candidate_id.is_not(None)
                if right_candidate_id
                else IdentitySuggestion.existing_account_id.is_not(None),
            )  # fmt: skip
        )
        report.created += 1
        return
    same_evidence = (existing.left_revision, existing.right_revision) == revisions
    if existing.status not in ("pending", "deferred"):
        if not same_evidence and existing.evidence_changed_at is None:
            existing.evidence_changed_at = now  # reviewed decisions are never rewritten; flag for a reviewer
            report.evidence_changed_on_reviewed += 1
        else:
            report.unchanged += 1
        return
    if same_evidence and existing.reason_codes == list(match.reason_codes):
        report.unchanged += 1
        return
    existing.left_revision, existing.right_revision = revisions
    existing.features, existing.reason_codes = match.features, list(match.reason_codes)
    existing.evidence_source_record_ids = evidence
    existing.version += 1
    existing.updated_at = now
    if match.resolution in STORED:
        existing.resolution = match.resolution
        report.recomputed += 1
    else:
        existing.status = "superseded"  # new evidence says distinct: the open suggestion no longer applies
        report.superseded += 1


# --- review ----------------------------------------------------------------------------------------------


def _digest(suggestion_id: uuid.UUID, action: str, expected_version: int, reason: str) -> str:
    payload = json.dumps([str(suggestion_id), action, expected_version, reason], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _replay(db: Session, org: uuid.UUID, command_id: uuid.UUID, digest: str) -> DecisionResult | None:
    prior = db.scalar(
        select(IdentityDecision).where(
            IdentityDecision.organization_id == org, IdentityDecision.command_id == command_id
        )
    )
    if prior is None:
        return None
    if prior.payload_digest != digest:
        raise Conflict("command_id was already used with a different payload")
    suggestion = db.scalar(
        select(IdentitySuggestion).where(
            IdentitySuggestion.organization_id == org, IdentitySuggestion.id == prior.suggestion_id
        )
    )
    if suggestion is None:  # pragma: no cover - FK guarantees it
        raise NotFound()
    return DecisionResult(suggestion, prior.id, True, list(prior.held_fact_ids), prior.link_id)


def held_facts(
    db: Session, org: uuid.UUID, link: CandidateAccountLink, source_record_id: uuid.UUID | None
) -> list[str]:
    """Current facts on the linked account that cite the candidate's source and were recorded after linking."""
    if source_record_id is None:
        return []
    successor = aliased(AccountFact)
    rows = db.scalars(
        select(AccountFact.id)
        .where(
            AccountFact.organization_id == org,
            AccountFact.account_id == link.account_id,
            AccountFact.source_record_id == source_record_id,
            AccountFact.created_at >= link.linked_at,
            ~exists().where(successor.organization_id == org, successor.supersedes_fact_id == AccountFact.id),
        )
        .order_by(AccountFact.created_at, AccountFact.id)
    )
    return [str(r) for r in rows]


def decide(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    suggestion_id: uuid.UUID,
    command_id: uuid.UUID,
    action: Action,
    expected_version: int,
    reason: str,
) -> DecisionResult:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    try:
        reason = policy.clean_text(reason, "reason", 1000)
    except policy.PolicyViolation as exc:
        raise InvalidRequest(str(exc)) from None
    if len(reason) < 3:
        raise InvalidRequest("reason must be 3-1000 characters")
    digest = _digest(suggestion_id, action, expected_version, reason)
    replay = _replay(db, org, command_id, digest)
    if replay is not None:
        return replay

    suggestion = db.scalar(
        select(IdentitySuggestion)
        .where(IdentitySuggestion.organization_id == org, IdentitySuggestion.id == suggestion_id)
        .with_for_update()
    )
    if suggestion is None:
        raise NotFound()
    replay = _replay(db, org, command_id, digest)  # an identical command may have committed while we waited
    if replay is not None:
        return replay
    if suggestion.version != expected_version:
        raise Conflict("the suggestion changed since you loaded it; reload and decide again")
    prior = suggestion.status
    next_status = TRANSITIONS[action].get(prior)
    if next_status is None:
        raise Conflict(f"cannot {action} a suggestion that is {prior}")

    now = clock.now()
    held: list[str] = []
    link_id: uuid.UUID | None = None
    active = db.scalar(
        select(CandidateAccountLink)
        .where(
            CandidateAccountLink.organization_id == org,
            CandidateAccountLink.suggestion_id == suggestion.id,
            CandidateAccountLink.unlinked_at.is_(None),
        )
        .with_for_update()
    )
    if action == "confirm_same_campus" and suggestion.existing_account_id is not None:
        taken = db.scalar(
            select(CandidateAccountLink.id).where(
                CandidateAccountLink.organization_id == org,
                CandidateAccountLink.candidate_id == suggestion.left_candidate_id,
                CandidateAccountLink.unlinked_at.is_(None),
            )
        )
        if taken is not None:
            raise Conflict("this candidate is already linked to an account; undo that link first")
        link = CandidateAccountLink(
            organization_id=org, candidate_id=suggestion.left_candidate_id, account_id=suggestion.existing_account_id,
            suggestion_id=suggestion.id, linked_by=actor.user_id, linked_at=now,
        )  # fmt: skip
        db.add(link)
        db.flush()
        link_id = link.id
    elif action == "undo" and active is not None:
        candidate = db.get(DiscoveryCandidate, suggestion.left_candidate_id)
        held = held_facts(db, org, active, candidate.source_record_id if candidate else None)
        link_id = active.id
        if held:
            next_status = "reallocation_review"  # never move or orphan evidence silently
        else:
            active.unlinked_at, active.unlinked_by = now, actor.user_id
    if action == "undo" and prior == "reallocation_review" and held:
        raise Conflict("facts recorded from this candidate's source still need correcting before undo")

    reverses = None
    if action == "undo":
        reversed_status = "confirmed" if prior == "reallocation_review" else prior
        reverses = db.scalar(
            select(IdentityDecision.id)
            .where(
                IdentityDecision.organization_id == org,
                IdentityDecision.suggestion_id == suggestion.id,
                IdentityDecision.next_status == reversed_status,
            )
            .order_by(IdentityDecision.recorded_at.desc(), IdentityDecision.id.desc())
            .limit(1)
        )
    updated = db.execute(
        update(IdentitySuggestion)
        .where(
            IdentitySuggestion.organization_id == org,
            IdentitySuggestion.id == suggestion.id,
            IdentitySuggestion.version == expected_version,
        )
        .values(
            status=next_status,
            version=expected_version + 1,
            reviewer_user_id=actor.user_id,
            reviewed_at=now,
            decision_reason=reason,
            updated_at=now,
        )  # fmt: skip
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:  # type: ignore[attr-defined]
        raise Conflict("the suggestion changed since you loaded it; reload and decide again")
    decision = IdentityDecision(
        organization_id=org, suggestion_id=suggestion.id, command_id=command_id, action=action,
        actor_user_id=actor.user_id, prior_status=prior, next_status=next_status, expected_version=expected_version,
        reason=reason, payload_digest=digest, held_fact_ids=held, link_id=link_id, reverses_decision_id=reverses,
        request_id=current_request_id(), recorded_at=now,
    )  # fmt: skip
    db.add(decision)
    management._audit(
        db,
        actor,
        clock,
        "identity.decision",
        suggestion.id,
        {"action": action, "prior_status": prior, "next_status": next_status, "held_facts": len(held),
         "link_id": str(link_id) if link_id else None},
        target_type="identity_suggestion",
    )  # fmt: skip
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = _replay(db, org, command_id, digest)  # a concurrent identical command won the race
        if replay is not None:
            return replay
        raise Conflict("the suggestion changed since you loaded it; reload and decide again") from None
    db.refresh(suggestion)
    return DecisionResult(suggestion, decision.id, False, held, link_id)


def suggestion_view(s: IdentitySuggestion, sides: dict[uuid.UUID, dict[str, Any]]) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": str(s.id),
        "status": s.status,
        "version": s.version,
        "resolution": s.resolution,
        "reason_codes": s.reason_codes,
        "features": s.features,
        "algorithm_version": s.algorithm_version,
        "left": sides.get(s.left_candidate_id),
        "right": sides.get(s.right_candidate_id or s.existing_account_id),  # type: ignore[arg-type]
        "right_kind": "candidate" if s.right_candidate_id else "account",
        "evidence_source_record_ids": s.evidence_source_record_ids,
        "evidence_changed_at": iso(s.evidence_changed_at),
        "reviewed_at": iso(s.reviewed_at),
        "decision_reason": s.decision_reason,
        "created_at": iso(s.created_at),
        # Explicit: a campus match says nothing about who decides purchases.
        "buying_authority": "unknown",
    }
