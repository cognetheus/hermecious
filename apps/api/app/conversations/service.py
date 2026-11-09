"""Conversation ownership commands and handoff tasks (P6.3, ADR-033). Human-only, atomic, idempotent, audited.

Every command runs in one transaction:
1. lock the conversation's owner row (`FOR UPDATE`) and check `expected_revision`;
2. check the idempotency key (same key + same request -> the recorded result; a changed request -> 409);
3. apply the transition; any change of who may send bumps `owner_generation` and **cancels every queued, not yet
   submitted dispatch attempt** in the same commit (fence);
4. append the event and the audit, and commit.

Only an interactive human session can issue commands: system and agent actors (no session verifier), classifiers
and models cannot change ownership. Releasing to the agent is an explicit human act and grants nothing else (consent,
P4.4 approval, the P5.5 gate and kill switches are all re-checked by the dispatch fence).
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.models import Role, User
from app.auth.service import Actor
from app.conversations.models import (
    ConversationOwner,
    ConversationOwnerEvent,
    DispatchAttempt,
    HandoffTask,
)
from app.core.clock import Clock
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.inbox.models import InboxThread

OWNERSHIP_VERSION = "ownership-1.0"
# command -> (states it may start from, resulting state, owner type); None = unchanged
TRANSITIONS: dict[str, tuple[tuple[str, ...], str | None, str | None]] = {
    "takeover": (("new", "agent_owned", "human_owned", "paused", "blocked"), "human_owned", "human"),
    "assign": (("new", "agent_owned", "human_owned", "paused"), "human_owned", "human"),
    "pause": (("new", "agent_owned", "human_owned"), "paused", None),
    "block": (("new", "agent_owned", "human_owned", "paused"), "blocked", None),
    "resolve": (("new", "agent_owned", "human_owned", "paused"), "resolved", None),
    "release_to_agent": (("human_owned", "paused"), "agent_owned", "agent"),
    "reopen": (("resolved", "blocked"), "new", "none"),
    "open_handoff": (("new", "agent_owned", "human_owned", "paused"), None, None),
    "acknowledge_handoff": (("new", "agent_owned", "human_owned", "paused", "blocked"), None, None),
}
CHANGES_AUTHORITY = {"takeover", "assign", "pause", "block", "resolve", "release_to_agent", "reopen"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _thread(db: Session, org: uuid.UUID, thread_id: uuid.UUID) -> InboxThread:
    thread = db.scalar(select(InboxThread).where(InboxThread.organization_id == org, InboxThread.id == thread_id))
    if thread is None:
        raise NotFound()
    return thread


def ensure(db: Session, org: uuid.UUID, thread_id: uuid.UUID, now: datetime) -> None:
    """Every conversation starts as `new` (triage), owned by nobody, generation 0. Never reset afterwards."""
    db.execute(
        insert(ConversationOwner)
        .values(id=uuid.uuid4(), organization_id=org, thread_id=thread_id, state="new", owner_type="none",
                owner_user_id=None, owner_generation=0, revision=1, updated_at=now)
        .on_conflict_do_nothing(constraint="uq_conversation_owners_thread")
    )  # fmt: skip


def _owner(db: Session, org: uuid.UUID, thread_id: uuid.UUID, *, lock: bool) -> ConversationOwner:
    query = select(ConversationOwner).where(
        ConversationOwner.organization_id == org, ConversationOwner.thread_id == thread_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    assert row is not None  # noqa: S101  # ensure() ran first
    return row


def _active_task(db: Session, thread_id: uuid.UUID) -> HandoffTask | None:
    return db.scalar(
        select(HandoffTask)
        .where(HandoffTask.thread_id == thread_id, HandoffTask.status.in_(("open", "acknowledged")))
        .with_for_update()
    )


def _assignee(db: Session, org: uuid.UUID, user_id: uuid.UUID) -> User:
    user = db.scalar(select(User).where(User.organization_id == org, User.id == user_id))
    if user is None or not user.active or user.role not in (Role.OWNER, Role.OPERATOR):
        raise Unprocessable("ASSIGNEE_INVALID: choose an active owner or operator of this organization")
    return user


def command(
    db: Session, *, actor: Actor, clock: Clock, thread_id: uuid.UUID, name: str, expected_revision: int,
    reason: str, idempotency_key: str, note: str = "", assignee_id: uuid.UUID | None = None, urgency: str = "normal",
    correlation_id: str | None = None,
) -> tuple[dict[str, Any], bool]:  # fmt: skip
    """Apply one ownership command. Returns (state view, applied_now)."""
    account_service._require(actor, Capability.MUTATE)
    if not actor.verifier:  # system, job, classifier or model actors have no interactive session
        raise Forbidden()
    if name in ("block", "reopen") and actor.role != Role.OWNER:
        raise Forbidden()
    if name not in TRANSITIONS:
        raise Unprocessable("UNKNOWN_COMMAND")
    org, now = actor.organization_id, clock.now()
    _thread(db, org, thread_id)
    request = _digest({
        "thread": str(thread_id), "command": name, "expected": expected_revision, "reason": reason, "note": note,
        "assignee": str(assignee_id) if assignee_id else None, "urgency": urgency,
    })  # fmt: skip
    ensure(db, org, thread_id, now)
    owner = _owner(db, org, thread_id, lock=True)
    prior = db.scalar(
        select(ConversationOwnerEvent).where(
            ConversationOwnerEvent.organization_id == org, ConversationOwnerEvent.idempotency_key == idempotency_key
        )
    )
    if prior is not None:
        db.rollback()
        if prior.request_digest != request or prior.thread_id != thread_id:
            raise Conflict("idempotency_key was already used for a different command")
        return view(db, org, thread_id), False
    if owner.revision != expected_revision:
        db.rollback()
        raise Conflict(f"the conversation changed (revision {owner.revision}); reload and retry")
    allowed, to_state, to_type = TRANSITIONS[name]
    if owner.state not in allowed:
        db.rollback()
        raise Conflict(f"cannot {name} a conversation that is {owner.state}")
    before_state, before_owner = owner.state, _owner_label(owner)
    canceled = 0
    task = _active_task(db, thread_id)
    if name in ("takeover", "assign"):
        target = actor.user_id if name == "takeover" else (assignee_id or uuid.UUID(int=0))
        _assignee(db, org, target)
        if owner.state == "human_owned" and owner.owner_user_id == target:
            db.rollback()
            raise Conflict("this person already owns the conversation")
        owner.owner_user_id = target
        if task is None:
            task = HandoffTask(organization_id=org, thread_id=thread_id, kind="handoff", reason=reason, urgency=urgency,
                               status="open", assigned_to=target, context_ref=f"thread:{thread_id}",
                               created_by=actor.user_id, created_at=now, version=1)  # fmt: skip
            db.add(task)
        else:
            task.assigned_to, task.version = target, task.version + 1
    elif name == "open_handoff":
        if task is not None:
            db.rollback()
            raise Conflict("this conversation already has an active handoff task")
        db.add(HandoffTask(organization_id=org, thread_id=thread_id, kind="handoff", reason=reason, urgency=urgency,
                           status="open", assigned_to=assignee_id and _assignee(db, org, assignee_id).id,
                           context_ref=f"thread:{thread_id}", created_by=actor.user_id, created_at=now,
                           version=1))  # fmt: skip
    elif name == "acknowledge_handoff":
        if task is None or task.status != "open":
            db.rollback()
            raise Conflict("there is no open handoff task to acknowledge")
        task.status, task.acknowledged_at, task.version = "acknowledged", now, task.version + 1
        task.assigned_to = task.assigned_to or actor.user_id
    elif name == "resolve" and task is not None:
        task.status, task.closed_at, task.version = "closed", now, task.version + 1
    if to_state is not None:
        owner.state = to_state
    if to_type is not None:
        owner.owner_type = to_type
        if to_type != "human":
            owner.owner_user_id = None
    if name in CHANGES_AUTHORITY:
        owner.owner_generation += 1
        canceled = cancel_queued(db, thread_id, "owner_changed", now)
    owner.revision += 1
    owner.updated_at = now
    db.add(ConversationOwnerEvent(
        organization_id=org, thread_id=thread_id, command=name, reason=reason, note=" ".join(note.split())[:300],
        from_state=before_state, to_state=owner.state, from_owner=before_owner, to_owner=_owner_label(owner),
        generation_after=owner.owner_generation, revision_after=owner.revision, canceled_attempts=canceled,
        actor_id=actor.user_id, correlation_id=correlation_id, idempotency_key=idempotency_key,
        request_digest=request, created_at=now,
    ))  # fmt: skip
    management._audit(db, actor, clock, f"conversation.{name}", thread_id,
                      {"from": before_state, "to": owner.state, "generation": owner.owner_generation,
                       "reason": reason, "canceled_attempts": canceled}, target_type="inbox_thread")  # fmt: skip
    db.commit()
    return view(db, org, thread_id), True


def cancel_queued(db: Session, thread_id: uuid.UUID, reason: str, now: datetime) -> int:
    """Fence: queued attempts can never be submitted once authority changed. Submitted ones are left as they are."""
    result = db.execute(
        update(DispatchAttempt)
        .where(DispatchAttempt.thread_id == thread_id, DispatchAttempt.state == "queued")
        .values(state="canceled", deny_reason=reason, updated_at=now, version=DispatchAttempt.version + 1)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _owner_label(owner: ConversationOwner) -> str | None:
    if owner.owner_type == "human":
        return f"user:{owner.owner_user_id}"
    return owner.owner_type if owner.owner_type != "none" else None


# --- reads -----------------------------------------------------------------------------------------------------------


def view(db: Session, org: uuid.UUID, thread_id: uuid.UUID) -> dict[str, Any]:
    owner = db.scalar(
        select(ConversationOwner).where(
            ConversationOwner.organization_id == org, ConversationOwner.thread_id == thread_id
        )
    )
    users = {u.id: (u.display_name or u.email_canonical.split("@")[0])
             for u in db.scalars(select(User).where(User.organization_id == org))}  # fmt: skip
    task = db.scalar(
        select(HandoffTask)
        .where(HandoffTask.organization_id == org, HandoffTask.thread_id == thread_id)
        .order_by(HandoffTask.created_at.desc(), HandoffTask.id.desc())
        .limit(1)
    )
    events = db.scalars(
        select(ConversationOwnerEvent)
        .where(ConversationOwnerEvent.organization_id == org, ConversationOwnerEvent.thread_id == thread_id)
        .order_by(ConversationOwnerEvent.revision_after)
    )
    attempts = db.scalars(
        select(DispatchAttempt)
        .where(DispatchAttempt.organization_id == org, DispatchAttempt.thread_id == thread_id)
        .order_by(DispatchAttempt.created_at, DispatchAttempt.id)
    )
    generation = owner.owner_generation if owner else 0
    return {
        "thread_id": str(thread_id), "state": owner.state if owner else "new",
        "owner_type": owner.owner_type if owner else "none",
        "owner": users.get(owner.owner_user_id) if owner and owner.owner_user_id else None,
        "owner_user_id": str(owner.owner_user_id) if owner and owner.owner_user_id else None,
        "owner_generation": generation, "revision": owner.revision if owner else 1,
        "auto_replies": "disabled",  # P6.5 is not implemented; nothing in P6.3 can send
        "handoff": None if task is None else {
            "id": str(task.id), "reason": task.reason, "urgency": task.urgency, "status": task.status,
            "assigned_to": users.get(task.assigned_to) if task.assigned_to else None,
            "created_at": task.created_at.isoformat(), "context_ref": task.context_ref,
        },
        "history": [
            {"command": e.command, "reason": e.reason, "from": e.from_state, "to": e.to_state,
             "generation": e.generation_after, "actor": users.get(e.actor_id), "at": e.created_at.isoformat(),
             "canceled_attempts": e.canceled_attempts}
            for e in events
        ],
        "attempts": [
            {"id": str(a.id), "state": a.state, "deny_reason": a.deny_reason, "queued_generation": a.owner_generation,
             "submitted_before_takeover": a.state in ("submitting", "accepted", "indeterminate")
             and a.owner_generation < generation}
            for a in attempts
        ],
        "policy_version": OWNERSHIP_VERSION,
    }  # fmt: skip


def handoff_queue(db: Session, org: uuid.UUID) -> list[dict[str, Any]]:
    users = {u.id: (u.display_name or u.email_canonical.split("@")[0])
             for u in db.scalars(select(User).where(User.organization_id == org))}  # fmt: skip
    rows = db.execute(
        select(HandoffTask, InboxThread.party_hint)
        .join(InboxThread, InboxThread.id == HandoffTask.thread_id)
        .where(HandoffTask.organization_id == org, HandoffTask.status.in_(("open", "acknowledged")))
        .order_by(HandoffTask.urgency.desc(), HandoffTask.created_at)
        .limit(100)
    ).all()
    return [
        {"id": str(t.id), "thread_id": str(t.thread_id), "address": hint, "reason": t.reason, "urgency": t.urgency,
         "status": t.status, "assigned_to": users.get(t.assigned_to) if t.assigned_to else None,
         "created_at": t.created_at.isoformat()}
        for t, hint in rows
    ]  # fmt: skip


def assignees(db: Session, org: uuid.UUID) -> list[dict[str, str]]:
    return [
        {"id": str(u.id), "name": u.display_name or u.email_canonical.split("@")[0], "role": u.role}
        for u in db.scalars(
            select(User)
            .where(User.organization_id == org, User.active.is_(True), User.role.in_((Role.OWNER, Role.OPERATOR)))
            .order_by(User.email_canonical)
        )
    ]
