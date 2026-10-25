"""Zero-egress sending simulator (P4.5, ADR-024).

A run is requested by an owner or operator for one campaign. It is executed by the allowlisted
`simulation.run` v1 job and considers at most 30 candidates: members first, then other campaign candidates.

**Per candidate**, in order:
1. contact present (else `invalid`);
2. membership not excluded;
3. latest draft;
4. a fresh P4.4 approval status: content approved and not stale;
5. a fresh P4.3 decision for the approval's exact contact and template;
6. only then, for fixture campaigns outside production, the fake transport.

All state is re-read from the database immediately before each item, so an opt-out, revocation, pause or kill
switch mid-run denies the remaining items. Items are unique per (run, account): a retried job converges on one
logical result per account, and the fake transport's `sim-` receipt is deterministic per logical item.

Nothing here sends, queues or schedules a real message, records consent or changes contact, draft or approval
state. `real_messages_sent` is 0, enforced by the database.
"""

import csv
import hashlib
import io
import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account
from app.approvals import service as approvals
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.campaigns import service as campaign_service
from app.campaigns.models import Campaign, CampaignAccount
from app.contacts.models import Contact
from app.core.clock import BUSINESS_TZ, Clock
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.core.settings import Settings
from app.drafts.models import Draft
from app.eligibility import policy
from app.eligibility import service as eligibility
from app.jobs import registry as job_registry
from app.jobs import service as job_service
from app.simulations.models import SimulationItem, SimulationRun
from app.simulations.transport import MAX_ATTEMPTS, FakeWhatsAppTransport

JOB_TYPE, JOB_VERSION = "simulation.run", 1
RUN_SECONDS = 45  # per attempt, inside the 60 s job lease; a retry resumes from the durable items
MONOTONIC = time.monotonic
SIMULATOR_VERSION = "simulator-1.0"
MAX_ITEMS = 30
LABEL = "SIMULATION ONLY — 0 real messages sent"
TERMINAL = ("completed", "cancelled", "failed")
# Reason code (after removing an `eligibility_` prefix) -> what is missing before real outreach.
PREREQUISITES = {
    "real opt-in": {
        "no_opt_in_permission",
        "permission_unverified",
        "permission_revoked",
        "purpose_not_covered",
        "permission_expired",
        "proof_stale",
        "proof_future_dated",
        "consent_wording_outdated",
        "permission_changed",
        "suppressed",
    },
    "official template approval": {"template_missing", "template_unverified", "template_rejected"},
    "fresh evidence": {
        "evidence_changed",
        "offer_changed",
        "offer_not_published",
        "assessment_superseded",
        "rules_changed",
        "evidence_quality_gate_closed",
        "draft_assessment_superseded",
        "draft_offer_changed",
        "account_archived",
    },
    "draft review": {
        "no_draft",
        "approval_not_reviewed",
        "approval_rejected",
        "approval_revoked",
        "approval_expired",
        "newer_revision_exists",
    },
    "campaign membership": {"not_approved_for_drafting", "excluded", "campaign_paused", "campaign_cancelled"},
    "contact on record": {"no_contact"},
}
PREFIXED = {"cited_fact_": "fresh evidence", "grounding_changed_": "fresh evidence", "verifier_": "draft review"}


def prerequisite(reason: str) -> str | None:
    code = reason.removeprefix("eligibility_")
    for name, codes in PREREQUISITES.items():
        if code in codes:
            return name
    return next((name for prefix, name in PREFIXED.items() if code.startswith(prefix)), None)


# Always outstanding before any real outreach, whatever this run shows.
STANDING_BLOCKERS = (
    "official WhatsApp template approval (P5; fixtures are simulation only)",
    "real 30-school evidence-quality audit (P3.4 EVAL-07)",
    "verified real opt-in evidence for real contacts",
)


class SimulatedWorkerCrash(RuntimeError):
    """`worker_restart_mock`: the first attempt stops part-way, as a killed worker would."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


# --- create / cancel -------------------------------------------------------------------------------------------


def _replay(db: Session, org: uuid.UUID, key: str, digest: str) -> SimulationRun | None:
    prior = db.scalar(
        select(SimulationRun).where(SimulationRun.organization_id == org, SimulationRun.idempotency_key == key)
    )
    if prior is not None and prior.request_digest != digest:
        raise Conflict("idempotency_key was already used for a different simulation request")
    return prior


def create_run(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    environment: str,
    campaign_id: uuid.UUID,
    scenario: str,
    max_items: int,
    idempotency_key: str,
) -> tuple[SimulationRun, bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    digest = _digest({"campaign": str(campaign_id), "scenario": scenario, "max_items": max_items})
    if (prior := _replay(db, org, idempotency_key, digest)) is not None:
        return prior, False
    campaign = campaign_service._campaign(db, org, campaign_id, lock=True)
    if (prior := _replay(db, org, idempotency_key, digest)) is not None:
        return prior, False
    mode = "fixture" if campaign.mode == "fixture" and environment != "production" else "readiness"
    if mode == "readiness" and scenario != "all_allow":
        raise InvalidRequest("scenarios alter fixture state only; a readiness run uses all_allow")
    now = clock.now()
    active = db.scalar(
        select(SimulationRun)
        .where(
            SimulationRun.organization_id == org,
            SimulationRun.campaign_id == campaign.id,
            SimulationRun.status.in_(("pending", "running")),
        )
        .with_for_update()
    )
    if active is not None and active.status == "running" and job_service.worker_gone(db, org, active.job_id):
        _finish(db, active, "failed", now, error_code="worker_lost")  # orphaned: its worker died for good
    elif active is not None:
        raise Conflict("a dry run is already active for this campaign; wait for it or cancel it")
    run = SimulationRun(
        organization_id=org,
        campaign_id=campaign.id,
        scenario=scenario,
        mode=mode,
        status="pending",
        max_items=max_items,
        considered=0,
        real_messages_sent=0,
        evaluated_at=now,
        policy_version=policy.POLICY_VERSION,
        simulator_version=SIMULATOR_VERSION,
        idempotency_key=idempotency_key,
        request_digest=digest,
        requested_by=actor.user_id,
        created_at=now,
        updated_at=now,
        version=1,
    )
    db.add(run)
    try:
        db.flush()
        receipt = job_service.enqueue_job(
            db,
            organization_id=org,
            environment=environment,
            job_type=JOB_TYPE,
            schema_version=JOB_VERSION,
            payload={"run_id": str(run.id)},
            idempotency_key=f"simulation.{run.id}",
            clock=clock,
        )
        run.job_id = receipt.job_id
        management._audit(
            db,
            actor,
            clock,
            "simulation.run_requested",
            campaign.id,
            {"run_id": str(run.id), "scenario": scenario, "max_items": max_items, "real_messages_sent": 0},
            target_type="campaign",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if (prior := _replay(db, org, idempotency_key, digest)) is not None:
            return prior, False
        raise Conflict("a dry run is already active for this campaign; wait for it or cancel it") from None
    return run, True


def _lock(db: Session, org: uuid.UUID, run_id: uuid.UUID) -> SimulationRun | None:
    """Lock and *reload* the row: sessions keep objects after commit, so a cancel written by another session
    would otherwise be invisible on an already-loaded run."""
    return db.scalar(
        select(SimulationRun)
        .where(SimulationRun.organization_id == org, SimulationRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def get_run(db: Session, org: uuid.UUID, campaign_id: uuid.UUID, run_id: uuid.UUID) -> SimulationRun:
    run = db.scalar(
        select(SimulationRun).where(
            SimulationRun.organization_id == org,
            SimulationRun.campaign_id == campaign_id,
            SimulationRun.id == run_id,
        )
    )
    if run is None:
        raise NotFound()
    return run


def cancel_run(db: Session, *, actor: Actor, clock: Clock, campaign_id: uuid.UUID, run_id: uuid.UUID) -> SimulationRun:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    get_run(db, org, campaign_id, run_id)
    run = _lock(db, org, run_id)
    assert run is not None  # noqa: S101
    if run.status in TERMINAL:
        db.rollback()
        return run
    now = clock.now()
    run.requested_cancel_at = run.requested_cancel_at or now
    if run.status == "pending":
        _finish(db, run, "cancelled", now)
        db.execute(
            text(
                "UPDATE jobs SET status = 'cancelled', finished_at = :now, updated_at = :now"
                " WHERE organization_id = :org AND id = :job AND status IN ('pending', 'retry_wait')"
            ),
            {"now": now, "org": org, "job": run.job_id},
        )
    elif job_service.worker_gone(db, org, run.job_id):  # orphaned: no worker will ever stop it
        _finish(db, run, "cancelled", now, error_code="worker_lost")
    else:
        run.version += 1
        run.updated_at = now
    management._audit(
        db,
        actor,
        clock,
        "simulation.run_cancel_requested",
        run.campaign_id,
        {"run_id": str(run.id), "status": run.status},
        target_type="campaign",
    )
    db.commit()
    return run


# --- worker ----------------------------------------------------------------------------------------------------


def handle_simulation_job(
    db: Session, ctx: job_registry.JobContext, payload: Any, load_settings: Callable[[], Settings]
) -> dict[str, Any]:
    """`load_settings` is called before every item, so a kill switch flipped mid-run applies immediately."""
    org, run_id = ctx.organization_id, uuid.UUID(str(payload.run_id))
    run = _lock(db, org, run_id)
    if run is None:
        raise job_registry.PermanentJobError("run_not_found")
    if run.status in TERMINAL:
        return {"run_id": str(run.id), "run_status": run.status, "skipped": True}
    if run.requested_cancel_at is not None:
        _finish(db, run, "cancelled", ctx.now)
        return {"run_id": str(run.id), "run_status": "cancelled"}
    run.status, run.started_at, run.updated_at = "running", run.started_at or ctx.now, ctx.now
    run.version += 1
    db.commit()
    try:
        return _execute(db, ctx, run_id, load_settings)
    except (job_registry.PermanentJobError, SimulatedWorkerCrash):
        raise
    except Exception:
        if ctx.attempt < ctx.max_attempts:
            raise
        db.rollback()
        run = _lock(db, org, run_id)
        if run is None or run.status != "running":
            return {"run_id": str(run_id), "skipped": True}
        _finish(db, run, "failed", ctx.now, error_code="worker_error")
        return {"run_id": str(run_id), "run_status": "failed"}


def candidates(db: Session, campaign: Campaign, limit: int, now: datetime) -> list[uuid.UUID]:
    """Members first (approved or excluded), then the other accounts the campaign preview considers."""
    org = campaign.organization_id
    members = set(
        db.scalars(
            select(CampaignAccount.account_id).where(
                CampaignAccount.organization_id == org, CampaignAccount.campaign_id == campaign.id
            )
        )
    )
    previewed = {uuid.UUID(c.account_id) for c in campaign_service._candidates(db, campaign, now)}
    return sorted(members | previewed, key=lambda a: (a not in members, str(a)))[:limit]


def _evaluation_time(run: SimulationRun) -> datetime:
    """`quiet_hours`: the request time if it is already outside business hours, else that day's closing time
    (Asia/Karachi), which is at most 9 hours ahead and never in the past."""
    at = run.evaluated_at
    if run.scenario != "quiet_hours" or policy.next_open(at) != at:
        return at
    day = at.astimezone(BUSINESS_TZ).date()
    return datetime.combine(day, policy.WORK_END, BUSINESS_TZ).astimezone(at.tzinfo)


def _execute(
    db: Session, ctx: job_registry.JobContext, run_id: uuid.UUID, load_settings: Callable[[], Settings]
) -> dict[str, Any]:
    org = ctx.organization_id
    started = MONOTONIC()
    run = _lock(db, org, run_id)
    assert run is not None  # noqa: S101
    campaign = campaign_service._campaign(db, org, run.campaign_id)
    if run.account_ids is None:  # frozen at the first attempt so retries see the same candidates and seq
        run.account_ids = [str(a) for a in candidates(db, campaign, run.max_items, run.evaluated_at)]
    db.commit()
    ids = [uuid.UUID(a) for a in run.account_ids]
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.organization_id == org, Account.id.in_(ids)))}
    pool = [accounts[a] for a in ids if a in accounts]
    transport = FakeWhatsAppTransport(run.scenario)
    now = _evaluation_time(run)
    done = {
        r.account_id: r
        for r in db.scalars(
            select(SimulationItem).where(SimulationItem.organization_id == org, SimulationItem.run_id == run_id)
        )
    }
    opt_outs = OptOuts(run.scenario)
    for seq, account in enumerate(pool, start=1):
        if account.id in done:
            continue  # recorded by an earlier attempt: one logical result per account
        if db.scalar(select(SimulationRun.requested_cancel_at).where(SimulationRun.id == run_id)) is not None:
            break
        if run.scenario == "worker_restart_mock" and ctx.attempt == 1 and seq > (len(pool) + 1) // 2:
            raise SimulatedWorkerCrash("worker_restart_mock")
        if MONOTONIC() - started > RUN_SECONDS:
            raise job_registry.TransientJobError("time_budget")  # the next attempt resumes after durable items
        accepted_so_far = sum(1 for r in done.values() if r.bucket == "accepted")
        settings = load_settings()
        item = _item(db, run, campaign, account, seq, now, settings, transport, accepted_so_far, opt_outs)
        db.add(item)
        db.commit()  # per-item progress is durable
        done[account.id] = item
    run = _lock(db, org, run_id)
    assert run is not None  # noqa: S101
    if run.status != "running":
        return {"run_id": str(run_id), "run_status": run.status, "skipped": True}
    status = "cancelled" if run.requested_cancel_at is not None else "completed"
    _finish(db, run, status, ctx.now)
    return {"run_id": str(run_id), "run_status": status, "considered": run.considered}


class OptOuts:
    """`opt_out_mid_run`: a simulated STOP from the second recipient that reaches the contact stage."""

    def __init__(self, scenario: str) -> None:
        self.active = scenario == "opt_out_mid_run"
        self.reached = 0
        self.contacts: set[uuid.UUID] = set()

    def suppressed(self, contact_id: uuid.UUID) -> bool:
        self.reached += 1
        if self.active and self.reached == 2:
            self.contacts.add(contact_id)
        return contact_id in self.contacts


def _item(
    db: Session,
    run: SimulationRun,
    campaign: Campaign,
    account: Account,
    seq: int,
    now: datetime,
    settings: Settings,
    transport: FakeWhatsAppTransport,
    accepted_so_far: int,
    opt_outs: OptOuts,
) -> SimulationItem:
    org = run.organization_id
    item = SimulationItem(
        organization_id=org,
        run_id=run.id,
        seq=seq,
        account_id=account.id,
        bucket="denied",
        reasons=[],
        lifecycle="not_attempted",
        attempts=0,
        policy_version=policy.POLICY_VERSION,
        evaluated_at=now,
        created_at=run.evaluated_at,
    )
    has_contact = db.scalar(
        select(Contact.id).where(Contact.organization_id == org, Contact.account_id == account.id).limit(1)
    )
    if has_contact is None:
        item.bucket, item.reasons = "invalid", ["no_contact"]
        return item
    member = db.scalar(
        select(CampaignAccount).where(
            CampaignAccount.organization_id == org,
            CampaignAccount.campaign_id == campaign.id,
            CampaignAccount.account_id == account.id,
        )
    )
    if member is None or member.stage == "excluded":
        item.reasons = ["excluded" if member is not None else "not_approved_for_drafting"]
        return item
    draft = db.scalar(
        select(Draft)
        .where(Draft.organization_id == org, Draft.campaign_id == campaign.id, Draft.account_id == account.id)
        .order_by(Draft.revision.desc())
        .limit(1)
    )
    if draft is None:
        item.reasons = ["no_draft"]
        return item
    item.draft_id, item.draft_revision = draft.id, draft.revision
    approval_now = now + approvals.APPROVAL_TTL + timedelta(seconds=1) if run.scenario == "stale_approval" else now
    status = approvals.status(db, draft, approval_now, settings)
    review = status["review"]
    if status["state"] != "approved_content" or review is None:
        item.reasons = [f"approval_{status['state']}", *status["stale_reasons"]]
        return item
    contact_id = uuid.UUID(review["contact_id"])
    item.contact_id, item.approval_id = contact_id, uuid.UUID(review["id"])
    item.content_digest = review["content_digest"]
    if opt_outs.suppressed(contact_id):
        item.reasons = ["suppressed", "simulated_opt_out"]
        return item
    offset = policy.DAILY_CAP - 1 if run.scenario == "quota" else 0
    decision = eligibility.decide(
        db,
        org=org,
        now=now,
        settings=settings,
        contact_id=contact_id,
        purpose=approvals.PURPOSE,
        campaign_id=campaign.id,
        template_ref=review["template_ref"],
        inbound_ref=None,
        usage=policy.Usage(org_business_initiated_today=offset + accepted_so_far),
    )
    item.permission_revision = decision["permission_revision"]
    codes = [r["code"] for r in decision["reasons"]]
    if decision["decision"] == "deny":
        item.reasons = codes
        return item
    if decision["decision"] == "defer":
        item.bucket, item.reasons = "deferred", codes
        item.next_window_at = datetime.fromisoformat(decision["next_window_at"])
        return item
    item.bucket = "accepted"
    if run.mode != "fixture":  # readiness runs never simulate delivery for real contacts
        item.bucket, item.reasons = "denied", ["readiness_only_no_simulated_delivery"]
        return item
    for attempt in range(1, MAX_ATTEMPTS + 1):
        item.attempts = attempt
        result = transport.submit(
            run_id=str(run.id), account_id=str(account.id), content_digest=str(item.content_digest), attempt=attempt
        )
        if result.status == "accepted":
            item.lifecycle, item.sim_receipt_id = "sim_delivered", result.sim_receipt_id
            return item
        item.reasons = [*item.reasons, f"sim_{result.status}_attempt_{attempt}"]
    item.lifecycle = "sim_failed"
    return item


def _finish(db: Session, run: SimulationRun, status: str, now: datetime, error_code: str | None = None) -> None:
    items = list(
        db.scalars(
            select(SimulationItem)
            .where(SimulationItem.organization_id == run.organization_id, SimulationItem.run_id == run.id)
            .order_by(SimulationItem.seq)
        )
    )
    report = build_report(run, items)
    run.status, run.finished_at, run.updated_at, run.error_code = status, now, now, error_code
    run.considered = len(items)
    run.report_json = report
    # Covers every item's outcome (not run-specific receipts), so equal states give equal digests.
    run.report_digest = _digest(
        [report, [(str(i.account_id), i.bucket, i.reasons, i.lifecycle, i.attempts) for i in items]]
    )
    run.version += 1
    db.commit()


# --- report ----------------------------------------------------------------------------------------------------


def _share(count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": count,
        "denominator": denominator,
        "percent": round(100 * count / denominator, 1) if denominator else None,
        "kind": "simulated",
    }


def build_report(run: SimulationRun, items: list[SimulationItem]) -> dict[str, Any]:
    considered = len(items)
    buckets = {b: sum(1 for i in items if i.bucket == b) for b in ("accepted", "denied", "deferred", "invalid")}
    delivered = sum(1 for i in items if i.lifecycle == "sim_delivered")
    failed = sum(1 for i in items if i.lifecycle == "sim_failed")
    prerequisites: dict[str, int] = {}
    for item in items:
        for name in sorted({p for r in item.reasons if (p := prerequisite(r))}):
            prerequisites[name] = prerequisites.get(name, 0) + 1
    assert sum(buckets.values()) == considered  # noqa: S101  # every item is in exactly one bucket
    return {
        "label": LABEL,
        "real_messages_sent": 0,
        "scenario": run.scenario,
        "mode": run.mode,
        "simulator_version": run.simulator_version,
        "policy_version": run.policy_version,
        "considered": considered,
        "buckets": {b: _share(n, considered) for b, n in buckets.items()},
        "lifecycle": {
            "sim_accepted": _share(delivered, buckets["accepted"]),
            "sim_delivered": _share(delivered, buckets["accepted"]),
            "sim_failed": _share(failed, buckets["accepted"]),
        },
        "reconciled": sum(buckets.values()) == considered and delivered + failed == buckets["accepted"],
        "missing_prerequisites": dict(sorted(prerequisites.items())),
        "standing_blockers": list(STANDING_BLOCKERS),
    }


def view_run(db: Session, run: SimulationRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "campaign_id": str(run.campaign_id),
        "scenario": run.scenario,
        "mode": run.mode,
        "status": run.status,
        "max_items": run.max_items,
        "considered": run.considered,
        "real_messages_sent": 0,
        "label": LABEL,
        "evaluated_at": run.evaluated_at.isoformat(),
        "policy_version": run.policy_version,
        "simulator_version": run.simulator_version,
        "report": run.report_json,
        "report_digest": run.report_digest,
        "error_code": run.error_code,
        "cancel_requested": run.requested_cancel_at is not None,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def items(db: Session, run: SimulationRun) -> list[dict[str, Any]]:
    names = {
        account_id: name
        for account_id, name in db.execute(
            select(Account.id, Account.canonical_name)
            .join(SimulationItem, SimulationItem.account_id == Account.id)
            .where(SimulationItem.organization_id == run.organization_id, SimulationItem.run_id == run.id)
        )
    }
    rows = db.scalars(
        select(SimulationItem)
        .where(SimulationItem.organization_id == run.organization_id, SimulationItem.run_id == run.id)
        .order_by(SimulationItem.seq)
    )
    return [
        {
            "seq": r.seq,
            "account_id": str(r.account_id),
            "account": names.get(r.account_id),
            "bucket": r.bucket,
            "reasons": r.reasons,
            "lifecycle": r.lifecycle,
            "sim_receipt_id": r.sim_receipt_id,
            "attempts": r.attempts,
            "draft_revision": r.draft_revision,
            "approval_id": str(r.approval_id) if r.approval_id else None,
            "permission_revision": r.permission_revision,
            "next_window_at": r.next_window_at.isoformat() if r.next_window_at else None,
        }
        for r in rows
    ]


def list_runs(db: Session, org: uuid.UUID, campaign_id: uuid.UUID) -> list[SimulationRun]:
    campaign_service._campaign(db, org, campaign_id)
    return list(
        db.scalars(
            select(SimulationRun)
            .where(SimulationRun.organization_id == org, SimulationRun.campaign_id == campaign_id)
            .order_by(SimulationRun.created_at.desc(), SimulationRun.id)
            .limit(50)
        )
    )


def _cell(value: Any) -> str:
    """CSV formula-injection guard: a leading = + - @ tab or CR is neutralised with a quote."""
    out = "" if value is None else str(value)
    return "'" + out if out[:1] in ("=", "+", "-", "@", "\t", "\r") else out


def export_csv(db: Session, run: SimulationRun) -> str:
    """Redacted: no phone numbers, message bodies or contact ids."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"# {LABEL}"])
    writer.writerow([f"# run {run.id}; scenario {run.scenario}; report digest {run.report_digest or 'pending'}"])
    writer.writerow(["seq", "account", "decision", "reasons", "simulated_lifecycle", "sim_receipt_id"])
    for row in items(db, run):
        writer.writerow(
            [
                _cell(row["seq"]),
                _cell(row["account"]),
                _cell(row["bucket"]),
                _cell(";".join(row["reasons"])),
                _cell(row["lifecycle"]),
                _cell(row["sim_receipt_id"]),
            ]
        )
    return buffer.getvalue()
