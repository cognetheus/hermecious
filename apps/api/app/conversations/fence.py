"""The final-dispatch fence (P6.3, ADR-033): the only gate a future automated reply (P6.5) may pass through.

There is no real send path. An attempt's transport is `simulation` (a database check), and P6.3 provides no
transport implementation at all; tests inject a fake one.

**Linearization.** `final_check` locks the conversation owner row `FOR SHARE` (a concurrent takeover takes
`FOR UPDATE`), re-checks everything authoritatively, and either denies or marks the attempt `submitting` before
any network call:
- if a takeover commits first, the generation no longer matches (or the queued attempt was already cancelled by the
  takeover), so the attempt is **denied** before submission;
- if the final check commits first, the attempt was **submitted before the takeover**. It cannot be recalled, and is
  shown as such. A timeout after submission is `indeterminate` and is never retried automatically.

**Checks, in order:** the attempt is still queued; the owner is the agent; the owner generation equals the expected
one and the one it was queued under; the reply proposal is this conversation's current, unrejected draft; the reply
has a P4.4-style approval (none exists before P6.5, so this denies); P4.3 eligibility for the contact and purpose
(suppression, consent, service window, template, accountable human); the global kill switch; the P5.5 live gate; and
the connection.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.conversations.models import ConversationOwner, DispatchAttempt
from app.core.errors import Conflict, NotFound
from app.core.settings import Settings
from app.eligibility import service as eligibility
from app.release import service as release
from app.replies import service as replies
from app.replies.models import ReplyProposalReview, ReplyProposalRow
from app.whatsapp import content
from app.whatsapp.models import ProviderConnection

FENCE_VERSION = "dispatch-fence-1.0"


@dataclass(frozen=True)
class Decision:
    allow: bool
    reasons: list[str] = field(default_factory=list)
    owner_generation: int | None = None


class Transport(Protocol):
    """A send. P6.3 has no implementation; tests inject a fake one. It returns accepted|rejected, or raises
    `TimeoutError` when the outcome is unknown."""

    def submit(self, attempt_id: uuid.UUID) -> str: ...


def _no_reply_approval(_proposal: ReplyProposalRow) -> bool:
    """P6.2 has no approval of reply drafts (only rejection); P6.5 must add one. Until then nothing passes."""
    return False


# The approval source a future P6.5 replaces. Tests substitute a fake to exercise the rest of the fence.
APPROVAL: Callable[[ReplyProposalRow], bool] = _no_reply_approval


def enqueue(
    db: Session, *, org: uuid.UUID, thread_id: uuid.UUID, reply_proposal_id: uuid.UUID, contact_id: uuid.UUID,
    connection_id: uuid.UUID, purpose: str, trace_id: str, idempotency_key: str, now: datetime,
) -> DispatchAttempt:  # fmt: skip
    """Queue an attempt under the current owner generation (idempotent per key). Queuing is not permission."""
    owner = db.scalar(
        select(ConversationOwner).where(
            ConversationOwner.organization_id == org, ConversationOwner.thread_id == thread_id
        )
    )
    if owner is None:
        raise NotFound()
    db.execute(
        insert(DispatchAttempt)
        .values(id=uuid.uuid4(), organization_id=org, thread_id=thread_id, reply_proposal_id=reply_proposal_id,
                contact_id=contact_id, provider_connection_id=connection_id, purpose=purpose,
                owner_generation=owner.owner_generation, transport="simulation", state="queued", deny_reason=None,
                trace_id=trace_id, idempotency_key=idempotency_key, created_at=now, updated_at=now, version=1)
        .on_conflict_do_nothing(constraint="uq_dispatch_attempts_idempotency")
    )  # fmt: skip
    db.commit()
    row = db.scalar(select(DispatchAttempt).where(DispatchAttempt.organization_id == org,
                                                  DispatchAttempt.idempotency_key == idempotency_key))  # fmt: skip
    assert row is not None  # noqa: S101
    return row


def final_check(
    db: Session, *, org: uuid.UUID, attempt_id: uuid.UUID, expected_generation: int, settings: Settings, now: datetime
) -> Decision:
    """Authoritative re-check immediately before submission. On allow, the attempt is `submitting` (committed)."""
    owner_lock = select(ConversationOwner).where(ConversationOwner.organization_id == org)
    attempt = db.scalar(select(DispatchAttempt).where(DispatchAttempt.organization_id == org,
                                                      DispatchAttempt.id == attempt_id))  # fmt: skip
    if attempt is None:
        raise NotFound()
    owner = db.scalar(owner_lock.where(ConversationOwner.thread_id == attempt.thread_id).with_for_update(read=True)
                      .execution_options(populate_existing=True))  # fmt: skip
    attempt = db.scalar(select(DispatchAttempt).where(DispatchAttempt.id == attempt_id).with_for_update()
                        .execution_options(populate_existing=True))  # fmt: skip
    assert owner is not None and attempt is not None  # noqa: S101
    reasons = _reasons(db, org, owner, attempt, expected_generation, settings, now)
    if reasons:
        if attempt.state == "queued":
            attempt.state, attempt.deny_reason = "denied", reasons[0][:64]
            attempt.updated_at, attempt.version = now, attempt.version + 1
        db.commit()
        return Decision(False, reasons, owner.owner_generation)
    attempt.state, attempt.updated_at, attempt.version = "submitting", now, attempt.version + 1
    db.commit()  # the fence point: from here the attempt may already be at the provider
    return Decision(True, [], owner.owner_generation)


def _reasons(
    db: Session, org: uuid.UUID, owner: ConversationOwner, attempt: DispatchAttempt, expected: int,
    settings: Settings, now: datetime,
) -> list[str]:  # fmt: skip
    if attempt.state != "queued":
        return [f"attempt_{attempt.state}"]
    if owner.state != "agent_owned" or owner.owner_type != "agent":
        return [f"owner_{owner.state}"]
    if owner.owner_generation != expected or attempt.owner_generation != expected:
        return ["owner_generation_mismatch"]
    proposal = db.scalar(select(ReplyProposalRow).where(ReplyProposalRow.organization_id == org,
                                                        ReplyProposalRow.id == attempt.reply_proposal_id))  # fmt: skip
    if proposal is None or proposal.thread_id != attempt.thread_id or proposal.status != "proposed":
        return ["reply_not_current"]
    lineage = replies.views(db, org, [proposal.inbound_message_id], content.keyring(settings), now)
    latest = lineage.get(proposal.inbound_message_id, [{}])[0]
    rejected = db.scalar(select(ReplyProposalReview.id).where(ReplyProposalReview.proposal_id == proposal.id))
    if latest.get("id") != str(proposal.id) or latest.get("stale") or rejected is not None:
        return ["reply_not_current"]
    if not APPROVAL(proposal):
        return ["reply_not_approved"]
    reasons: list[str] = []
    decision: dict[str, Any] = eligibility.decide(
        db, org=org, now=now, settings=settings, contact_id=attempt.contact_id, purpose=attempt.purpose,  # type: ignore[arg-type]
        campaign_id=None, template_ref=None, inbound_ref=None,
    )  # fmt: skip
    if decision["decision"] != "allow_for_simulation":
        reasons += [f"eligibility_{r['code']}" for r in decision["reasons"]] or [f"eligibility_{decision['decision']}"]
    if settings.outreach_kill_switch:
        reasons.append("kill_switch_engaged")
    if (gate := release.live_gate(settings)) is not None:
        reasons.append(f"live_gate_{gate}")
    connection = db.scalar(select(ProviderConnection).where(ProviderConnection.id == attempt.provider_connection_id))
    if connection is None or not connection.enabled or connection.organization_id != org:
        reasons.append("connection_unavailable")
    return reasons


def submit(db: Session, *, org: uuid.UUID, attempt_id: uuid.UUID, transport: Transport, now: datetime) -> str:
    """Record the outcome of a submission that passed the fence. Unknown outcomes are never retried."""
    attempt = db.scalar(select(DispatchAttempt).where(DispatchAttempt.organization_id == org,
                                                      DispatchAttempt.id == attempt_id))  # fmt: skip
    if attempt is None or attempt.state != "submitting":
        raise Conflict("only an attempt that passed the final check can be submitted")
    try:
        outcome = transport.submit(attempt_id)
    except TimeoutError:
        outcome = "indeterminate"
    attempt = db.scalar(select(DispatchAttempt).where(DispatchAttempt.id == attempt_id).with_for_update()
                        .execution_options(populate_existing=True))  # fmt: skip
    assert attempt is not None  # noqa: S101
    attempt.state = outcome if outcome in ("accepted", "rejected", "indeterminate") else "indeterminate"
    attempt.updated_at, attempt.version = now, attempt.version + 1
    db.commit()
    return attempt.state
