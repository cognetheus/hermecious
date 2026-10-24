"""Evidence quality evaluation (P3.4, ADR-019).

A run freezes a deterministic sample of up to 30 distinct eligible accounts:
every account is ordered by `sha256(seed:account_id)` and the first 30 are
taken. It records every **displayed factual claim** in that sample, which
covers three kinds of item:
1. each current source-supported fact (shown as evidence);
2. each P3.2 statement in an `observed` or `conflicting` state;
3. each P3.3 dimension shown as `strong` or `moderate`.

Hypotheses, unknowns and questions are labelled as such and are not
assertions.

**Humans adjudicate every item.** `supported` is refused when the cited
source is not currently usable or the evidence is contradicted.

**The metric is supported / all adjudicated items.** A run passes only if:
- its corpus is 30 real accounts;
- the ratio is at least 90%;
- no failed item is still displayed as fact.

Synthetic, insufficient or empty corpora never pass. Remediation demotes a
failed fact through the P1.4 correction chain and records the link; a
`post_remediation` run re-samples the same accounts and keeps the baseline
intact.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account, AccountFact, AccountStatus, SourceRecord, Vertical
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.evaluation.models import EvidenceEvalItem, EvidenceEvalRemediation, EvidenceEvalRun, EvidenceEvalVerdict
from app.qualification.models import Assessment
from app.research.service import associated_sources
from app.signals import rubric as signal_rubric
from app.signals.models import SchoolSignalSnapshot

TARGET_ACCOUNTS = 30
THRESHOLD = 0.9
SELECTION_METHOD = "sha256(seed:account_id) ascending; first 30 distinct eligible accounts"
SYNTHETIC_PROVIDERS = frozenset({"fixture_lahore_schools", "fixture"})
FAILING = frozenset({"unsupported", "contradicted", "stale", "unverifiable"})


# --- corpus -----------------------------------------------------------------------------------------------


def _current_facts(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> list[tuple[AccountFact, SourceRecord | None]]:
    successor = aliased(AccountFact)
    rows = db.execute(
        select(AccountFact, SourceRecord)
        .outerjoin(
            SourceRecord, (SourceRecord.organization_id == org) & (SourceRecord.id == AccountFact.source_record_id)
        )
        .where(
            AccountFact.organization_id == org,
            AccountFact.account_id == account_id,
            ~exists().where(successor.organization_id == org, successor.supersedes_fact_id == AccountFact.id),
        )
        .order_by(AccountFact.id)
    ).all()
    return [(f, s) for f, s in rows]


def provenance(db: Session, org: uuid.UUID, account: Account) -> str:
    """`real`, `synthetic` or `unsourced`: only accounts with real, non-fixture sources count toward the gate."""
    source_ids = set(associated_sources(db, org, account.id))
    providers = (
        set(
            db.scalars(
                select(SourceRecord.provider).where(
                    SourceRecord.organization_id == org, SourceRecord.id.in_(source_ids)
                )
            )
        )
        if source_ids
        else set()
    )
    if "(synthetic)" in account.canonical_name.casefold() or providers & SYNTHETIC_PROVIDERS:
        return "synthetic"
    return "real" if providers else "unsourced"


def _evidence(fact: AccountFact, source: SourceRecord | None) -> signal_rubric.EvidenceFact:
    return signal_rubric.EvidenceFact(
        fact_id=str(fact.id),
        claim_type=fact.claim_type,
        value=fact.typed_value_json,
        verification_status=fact.verification_status,
        observed_at=fact.observed_at,
        source_id=str(source.id) if source else None,
        storage_class=source.permitted_storage_class if source else None,
        source_expires_at=source.expires_at if source else None,
    )


def _citation(source: SourceRecord | None) -> dict[str, Any]:
    if source is None:
        return {"source_id": None}
    url = source.source_url if source.source_url.startswith("https://") else None  # never render other schemes
    return {
        "source_id": str(source.id),
        "provider": source.provider,
        "source_url": url,
        "storage_class": source.permitted_storage_class,
        "rights_policy_version": source.rights_policy_version,
        "expires_at": source.expires_at.isoformat() if source.expires_at else None,
    }


def displayed_claims(db: Session, org: uuid.UUID, account_id: uuid.UUID, now: datetime) -> list[dict[str, Any]]:
    """Everything this account currently displays as fact (rights-safe summaries; no excerpts)."""
    facts = _current_facts(db, org, account_id)
    by_id = {str(f.id): (f, s) for f, s in facts}
    items: list[dict[str, Any]] = []
    for fact, source in facts:
        if fact.verification_status != "source_supported":
            continue  # hypotheses are displayed as unverified, never as fact
        value = ", ".join(f"{k}: {v}" for k, v in sorted(fact.typed_value_json.items()))
        items.append(
            {
                "item_kind": "fact",
                "ref": str(fact.id),
                "display_text": f"{fact.claim_type}: {value}",
                "fact_ids": [str(fact.id)],
                "citations": [_citation(source)],
                "eligibility": signal_rubric.eligibility(_evidence(fact, source), now),
            }
        )

    def eligibility_of(fact_ids: list[str], conflicting: bool) -> str:
        if conflicting:
            return "contradicted"
        states = {
            signal_rubric.eligibility(_evidence(*by_id[i]), now) if i in by_id else "superseded" for i in fact_ids
        }
        return "usable" if states == {"usable"} else sorted(states - {"usable"})[0]

    snapshot = db.scalar(
        select(SchoolSignalSnapshot)
        .where(SchoolSignalSnapshot.organization_id == org, SchoolSignalSnapshot.account_id == account_id)
        .order_by(SchoolSignalSnapshot.created_at.desc(), SchoolSignalSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is not None:
        for key in signal_rubric.KEYS:
            signal = snapshot.signals_json["signals"].get(key, {})
            if signal.get("state") not in ("observed", "conflicting"):
                continue
            ids = signal["fact_ids"] or signal["conflicting_fact_ids"]
            items.append(
                {
                    "item_kind": "signal",
                    "ref": f"{snapshot.id}:{key}",
                    "display_text": signal["statement"],
                    "fact_ids": ids,
                    "citations": [_citation(by_id[i][1]) for i in ids if i in by_id],
                    "eligibility": eligibility_of(ids, signal["state"] == "conflicting"),
                }
            )
    assessment = db.scalar(
        select(Assessment)
        .where(Assessment.organization_id == org, Assessment.account_id == account_id)
        .order_by(Assessment.revision.desc())
        .limit(1)
    )
    if assessment is not None:
        for dim in ("customer_fit", "need_evidence", "accessibility", "delivery_fit"):
            value = getattr(assessment, dim)
            if value not in ("strong", "moderate"):
                continue
            explanation = assessment.explanation_json["dimensions"][dim]
            ids = explanation.get("fact_ids", [])
            items.append(
                {
                    "item_kind": "dimension",
                    "ref": f"{assessment.id}:{dim}",
                    "display_text": f"{dim}: {value}. {explanation['reason']}",
                    "fact_ids": ids,
                    "citations": [_citation(by_id[i][1]) for i in ids if i in by_id],
                    "eligibility": eligibility_of(ids, False) if ids else "unverifiable",
                }
            )
    return items


def _eligible_accounts(db: Session, org: uuid.UUID) -> list[Account]:
    return list(
        db.scalars(
            select(Account)
            .join(Vertical, Vertical.id == Account.vertical_id)
            .where(
                Account.organization_id == org,
                Account.status != AccountStatus.EXCLUDED,
                Account.city == "Lahore",
                Vertical.slug == "schools",
            )
            .order_by(Account.id)
        )
    )


def _order(seed: str, account_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{seed}:{account_id}".encode()).hexdigest()


# --- runs -----------------------------------------------------------------------------------------------------


def create_run(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    kind: str,
    seed: str,
    idempotency_key: str,
    baseline_run_id: uuid.UUID | None = None,
    allow_synthetic: bool = False,
) -> tuple[EvidenceEvalRun, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    prior = db.scalar(
        select(EvidenceEvalRun).where(
            EvidenceEvalRun.organization_id == org, EvidenceEvalRun.idempotency_key == idempotency_key
        )
    )
    if prior is not None:
        same = (prior.kind, prior.seed, prior.baseline_run_id) == (kind, seed, baseline_run_id)
        if not same or (prior.corpus_status == "SYNTHETIC_CORPUS") != allow_synthetic and allow_synthetic:
            raise Conflict("idempotency_key was already used for a different evaluation request")
        return prior, False
    if allow_synthetic and environment == "production":
        raise InvalidRequest("synthetic corpora are not allowed in production")
    now = clock.now()
    excluded: dict[str, str] = {}
    if kind == "post_remediation":
        baseline = db.scalar(
            select(EvidenceEvalRun).where(EvidenceEvalRun.organization_id == org, EvidenceEvalRun.id == baseline_run_id)
        )
        if baseline is None:
            raise NotFound()
        if baseline.kind != "baseline" or baseline.finalized_at is None:
            raise Conflict("a post-remediation run needs a finalized baseline run")
        accounts = [a for a in _eligible_accounts(db, org) if str(a.id) in set(baseline.account_ids)]
        seed = baseline.seed
        allow_synthetic = baseline.corpus_status == "SYNTHETIC_CORPUS"
    elif kind == "baseline" and baseline_run_id is None:
        accounts = _eligible_accounts(db, org)
    else:
        raise InvalidRequest("baseline runs take no baseline_run_id; post-remediation runs need one")
    seen_campus: set[tuple[str, str]] = set()
    chosen: list[tuple[Account, str]] = []
    for account in sorted(accounts, key=lambda a: _order(seed, a.id)):
        origin = provenance(db, org, account)
        campus = (account.normalized_name, (account.locality or "").casefold())
        if campus in seen_campus:
            excluded[str(account.id)] = "duplicate_campus_record"
        elif origin == "unsourced":
            excluded[str(account.id)] = "no_sources"
        elif origin == "synthetic" and not allow_synthetic:
            excluded[str(account.id)] = "synthetic_not_eligible"
        elif len(chosen) < TARGET_ACCOUNTS:
            seen_campus.add(campus)
            chosen.append((account, origin))
    real = sum(1 for _, o in chosen if o == "real")
    synthetic = len(chosen) - real
    status = "SYNTHETIC_CORPUS" if synthetic else ("OK" if real >= TARGET_ACCOUNTS else "INSUFFICIENT_CORPUS")
    drafts = [(a.id, origin == "real", d) for a, origin in chosen for d in displayed_claims(db, org, a.id, now)]
    fingerprint = hashlib.sha256(
        json.dumps(
            sorted(
                [
                    str(aid),
                    d["item_kind"],
                    d["ref"],
                    d["fact_ids"],
                    d["eligibility"],
                    [c.get("rights_policy_version") for c in d["citations"]],
                ]
                for aid, _, d in drafts
            )
            + [sorted(str(a.id) for a, _ in chosen)],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    run = EvidenceEvalRun(
        organization_id=org,
        kind=kind,
        baseline_run_id=baseline_run_id,
        idempotency_key=idempotency_key,
        selection_method=SELECTION_METHOD,
        seed=seed,
        account_ids=sorted(str(a.id) for a, _ in chosen),
        excluded_accounts=dict(sorted(excluded.items())[:200]),
        corpus_fingerprint=fingerprint,
        corpus_status=status,
        real_accounts=real,
        synthetic_accounts=synthetic,
        version=1,
        created_by=actor.user_id,
        created_at=now,
    )
    db.add(run)
    try:
        db.flush()
        for account_id, is_real, d in drafts:
            db.add(
                EvidenceEvalItem(
                    organization_id=org,
                    run_id=run.id,
                    account_id=account_id,
                    item_kind=d["item_kind"],
                    ref=d["ref"],
                    display_text=d["display_text"][:2000],
                    fact_ids=d["fact_ids"],
                    citations=d["citations"],
                    real_provenance=is_real,
                    eligibility_at_freeze=d["eligibility"],
                    version=1,
                )
            )
        management._audit(
            db,
            actor,
            clock,
            "evaluation.run_created",
            run.id,
            {
                "kind": kind,
                "accounts": len(chosen),
                "items": len(drafts),
                "corpus_status": status,
                "fingerprint": fingerprint,
            },
            target_type="evidence_eval",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(
            select(EvidenceEvalRun).where(
                EvidenceEvalRun.organization_id == org, EvidenceEvalRun.idempotency_key == idempotency_key
            )
        )
        if prior is None:
            raise Conflict("concurrent evaluation request did not commit; retry") from None
        return prior, False
    return run, True


def _run(db: Session, org: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False) -> EvidenceEvalRun:
    query = select(EvidenceEvalRun).where(EvidenceEvalRun.organization_id == org, EvidenceEvalRun.id == run_id)
    run = db.scalar(query.with_for_update() if lock else query)
    if run is None:
        raise NotFound()
    return run


def _item(db: Session, org: uuid.UUID, run_id: uuid.UUID, item_id: uuid.UUID) -> EvidenceEvalItem:
    item = db.scalar(
        select(EvidenceEvalItem)
        .where(
            EvidenceEvalItem.organization_id == org, EvidenceEvalItem.run_id == run_id, EvidenceEvalItem.id == item_id
        )
        .with_for_update()
    )
    if item is None:
        raise NotFound()
    return item


def current_eligibility(db: Session, org: uuid.UUID, item: EvidenceEvalItem, now: datetime) -> str:
    """The cited evidence's state now (re-checked at adjudication and finalization)."""
    if item.eligibility_at_freeze == "contradicted":
        return "contradicted"
    if not item.fact_ids:
        return "unverifiable"
    facts = {str(f.id): (f, s) for f, s in _current_facts(db, org, item.account_id)}
    states = set()
    for fact_id in item.fact_ids:
        if fact_id not in facts:
            states.add("superseded")
        else:
            states.add(signal_rubric.eligibility(_evidence(*facts[fact_id]), now))
    return "usable" if states == {"usable"} else sorted(states - {"usable"})[0]


def adjudicate(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    verdict: str,
    reason: str,
    expected_version: int,
) -> EvidenceEvalItem:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    run = _run(db, org, run_id, lock=True)
    if run.finalized_at is not None:
        raise Conflict("this evaluation is finalized; start a post-remediation run")
    item = _item(db, org, run_id, item_id)
    if item.version != expected_version:
        raise Conflict("this item changed since you loaded it; reload and review again")
    reason = " ".join(reason.split())
    if not 3 <= len(reason) <= 1000:
        raise InvalidRequest("reason must be 3-1000 characters")
    now = clock.now()
    state = current_eligibility(db, org, item, now)
    if verdict == "supported" and state != "usable":
        raise Conflict(f"cannot be supported: cited evidence is {state}")
    revision = (
        int(
            db.scalar(
                select(func.coalesce(func.max(EvidenceEvalVerdict.revision), 0)).where(
                    EvidenceEvalVerdict.organization_id == org, EvidenceEvalVerdict.item_id == item.id
                )
            )
            or 0
        )
        + 1
    )
    db.add(
        EvidenceEvalVerdict(
            organization_id=org,
            item_id=item.id,
            revision=revision,
            verdict=verdict,
            reason=reason,
            reviewer_id=actor.user_id,
            created_at=now,
        )
    )
    item.verdict = verdict
    item.version += 1
    run.version += 1
    db.commit()
    return item


def still_displayed(db: Session, org: uuid.UUID, item: EvidenceEvalItem, now: datetime) -> bool:
    current = {d["item_kind"] + "|" + d["ref"]: d for d in displayed_claims(db, org, item.account_id, now)}
    if item.item_kind == "fact":
        return f"fact|{item.ref}" in current
    key = item.ref.split(":", 1)[1]
    return any(
        k.startswith(f"{item.item_kind}|") and k.endswith(f":{key}") and d["display_text"] == item.display_text
        for k, d in current.items()
    )


def decide_result(corpus_status: str, supported: int, total: int, displayed_failures: int) -> tuple[str, str]:
    """Pure gate decision. The denominator is every adjudicated displayed claim; 0/0 never passes."""
    if corpus_status != "OK":
        return "BLOCKED", f"corpus is {corpus_status.lower()}: needs 30 real accounts"
    if total == 0:
        return "FAILED", "no displayed factual claims to evaluate (0/0 never passes)"
    if supported * 10 < total * 9:  # exactly 90% in integers: 18/20 passes, 17/20 does not
        return "FAILED", f"{supported}/{total} supported is below 90%"
    if displayed_failures:
        return "FAILED", f"{displayed_failures} failed claim(s) are still displayed as fact"
    return "PASSED", f"{supported}/{total} supported; no failures displayed"


def finalize(db: Session, *, actor: Actor, clock: Clock, run_id: uuid.UUID, expected_version: int) -> EvidenceEvalRun:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    run = _run(db, org, run_id, lock=True)
    if run.finalized_at is not None:
        db.rollback()
        return run  # replay-safe
    if run.version != expected_version:
        raise Conflict("this evaluation changed since you loaded it; reload")
    items = list(
        db.scalars(
            select(EvidenceEvalItem).where(EvidenceEvalItem.organization_id == org, EvidenceEvalItem.run_id == run.id)
        )
    )
    pending = [i for i in items if i.verdict is None]
    if pending:
        raise Conflict(f"incomplete: {len(pending)} item(s) still need a verdict")
    now = clock.now()
    # A supported verdict whose evidence lapsed before finalization no longer counts.
    supported = [i for i in items if i.verdict == "supported" and current_eligibility(db, org, i, now) == "usable"]
    failed = [i for i in items if i not in supported]
    displayed_failures = sum(1 for i in failed if still_displayed(db, org, i, now))
    run.numerator, run.denominator, run.still_displayed_failures = len(supported), len(items), displayed_failures
    run.result, run.result_reason = decide_result(run.corpus_status, len(supported), len(items), displayed_failures)
    run.finalized_at, run.finalized_by = now, actor.user_id
    run.version += 1
    management._audit(
        db,
        actor,
        clock,
        "evaluation.run_finalized",
        run.id,
        {
            "result": run.result,
            "numerator": run.numerator,
            "denominator": run.denominator,
            "still_displayed_failures": displayed_failures,
            "corpus_status": run.corpus_status,
        },
        target_type="evidence_eval",
    )
    db.commit()
    return run


def remediate(
    db: Session, *, actor: Actor, clock: Clock, run_id: uuid.UUID, item_id: uuid.UUID, reason: str
) -> EvidenceEvalRemediation:
    """Demote a failed displayed fact to an unverified hypothesis via the P1.4 correction chain (history kept)."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    _run(db, org, run_id)
    item = _item(db, org, run_id, item_id)
    if item.verdict not in FAILING:
        raise Conflict("only failed items are remediated")
    if item.item_kind != "fact":
        raise Conflict(
            "remediate the cited facts; derived statements follow when the brief and assessment are regenerated"
        )
    existing = db.scalar(
        select(EvidenceEvalRemediation).where(
            EvidenceEvalRemediation.organization_id == org, EvidenceEvalRemediation.item_id == item.id
        )
    )
    if existing is not None:
        return existing  # replay-safe
    fact = db.scalar(
        select(AccountFact).where(AccountFact.organization_id == org, AccountFact.id == uuid.UUID(item.ref))
    )
    if fact is None:
        raise NotFound()
    note = " ".join(reason.split())
    if not 3 <= len(note) <= 600:
        raise InvalidRequest("reason must be 3-600 characters")
    correction = management.correct_fact(
        db,
        actor=actor,
        clock=clock,
        account_id=fact.account_id,
        fact_id=fact.id,
        reason=f"Evidence evaluation {run_id} ({item.verdict}): {note}",
        data=management.FactInput(
            claim_type=fact.claim_type,
            value=fact.typed_value_json,
            verification_status="hypothesis",
            confidence_label="unknown",
            observed_at=fact.observed_at,
        ),
    )
    link = EvidenceEvalRemediation(
        organization_id=org,
        item_id=item.id,
        correction_fact_id=correction.id,
        reason=note,
        created_by=actor.user_id,
        created_at=clock.now(),
    )
    db.add(link)
    db.commit()
    return link


# --- read models ------------------------------------------------------------------------------------------------


def state(run: EvidenceEvalRun, pending: int) -> str:
    if run.result:
        return run.result
    if run.corpus_status != "OK":
        return "BLOCKED"
    return "INCOMPLETE" if pending else "READY_TO_FINALIZE"


def run_view(db: Session, run: EvidenceEvalRun, *, with_items: bool) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(EvidenceEvalItem)
            .where(EvidenceEvalItem.organization_id == run.organization_id, EvidenceEvalItem.run_id == run.id)
            .order_by(EvidenceEvalItem.account_id, EvidenceEvalItem.item_kind, EvidenceEvalItem.ref)
        )
    )
    pending = sum(1 for i in items if i.verdict is None)
    covered = {i.account_id for i in items}
    body: dict[str, Any] = {
        "id": str(run.id),
        "kind": run.kind,
        "baseline_run_id": str(run.baseline_run_id) if run.baseline_run_id else None,
        "state": state(run, pending),
        "result_reason": run.result_reason,
        "selection_method": run.selection_method,
        "seed": run.seed,
        "corpus_fingerprint": run.corpus_fingerprint,
        "corpus_status": run.corpus_status,
        "accounts": len(run.account_ids),
        "real_accounts": run.real_accounts,
        "synthetic_accounts": run.synthetic_accounts,
        "accounts_with_claims": len(covered),
        "accounts_without_claims": len(run.account_ids) - len(covered),
        "excluded_accounts": run.excluded_accounts,
        "items": len(items),
        "pending": pending,
        "numerator": run.numerator,
        "denominator": run.denominator,
        "ratio": (run.numerator / run.denominator) if run.denominator and run.numerator is not None else None,
        "still_displayed_failures": run.still_displayed_failures,
        "version": run.version,
        "created_at": run.created_at.isoformat(),
        "finalized_at": run.finalized_at.isoformat() if run.finalized_at else None,
    }
    if with_items:
        remediated = (
            {
                r.item_id: str(r.correction_fact_id)
                for r in db.scalars(
                    select(EvidenceEvalRemediation).where(
                        EvidenceEvalRemediation.organization_id == run.organization_id,
                        EvidenceEvalRemediation.item_id.in_([i.id for i in items]),
                    )
                )
            }
            if items
            else {}
        )
        body["item_list"] = [
            {
                "id": str(i.id),
                "account_id": str(i.account_id),
                "item_kind": i.item_kind,
                "ref": i.ref,
                "display_text": i.display_text,
                "fact_ids": i.fact_ids,
                "citations": i.citations,
                "real_provenance": i.real_provenance,
                "eligibility_at_freeze": i.eligibility_at_freeze,
                "verdict": i.verdict,
                "version": i.version,
                "remediation_fact_id": remediated.get(i.id),
            }
            for i in items
        ]
    return body


def gate(db: Session, org: uuid.UUID) -> dict[str, Any]:
    """Fail-closed downstream enrollment gate: only a finalized, real, PASSED evaluation opens it."""
    latest = db.scalar(
        select(EvidenceEvalRun)
        .where(EvidenceEvalRun.organization_id == org, EvidenceEvalRun.finalized_at.is_not(None))
        .order_by(EvidenceEvalRun.finalized_at.desc())
        .limit(1)
    )
    if latest is None:
        return {"enrollment_allowed": False, "status": "BLOCKED", "reason": "no finalized evidence evaluation"}
    allowed = latest.result == "PASSED" and latest.corpus_status == "OK"
    return {
        "enrollment_allowed": allowed,
        "status": latest.result,
        "reason": latest.result_reason,
        "run_id": str(latest.id),
    }
