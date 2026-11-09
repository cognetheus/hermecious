"""Conversation ownership, handoff tasks and the dispatch fence (P6.3, ADR-033).

The conversation is the P5.4 inbox thread; nothing here forks a second inbox.
- `ConversationOwner`: exactly one row per thread. `state` and `owner_type` are separate from provider status and
  from any sending permission. `owner_generation` only ever increases (a database trigger enforces it) and every
  ownership change bumps it; `revision` bumps on every command (optimistic concurrency).
- `ConversationOwnerEvent`: the append-only history of every command, with actor, reason, correlation id and a
  unique idempotency key.
- `HandoffTask`: at most one active (open or acknowledged) task per conversation; a de-identified reason and a
  context reference, never message content or student data.
- `DispatchAttempt`: the fenced record a future automated reply (P6.5) must pass through. The only transport the
  database accepts is `simulation`: no real send path exists in P6.3.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

STATES = ("new", "agent_owned", "human_owned", "paused", "blocked", "resolved")
OWNER_TYPES = ("none", "agent", "human")
COMMANDS = ("takeover", "assign", "pause", "block", "resolve", "release_to_agent", "reopen", "open_handoff",
            "acknowledge_handoff")  # fmt: skip
REASONS = ("human_requested", "unknown_offer", "sensitive", "conflicting_facts", "operator_takeover", "manual",
           "unmatched_contact", "quality_concern", "resolved_by_operator", "agent_release_approved")  # fmt: skip
ATTEMPT_STATES = ("queued", "denied", "canceled", "submitting", "accepted", "rejected", "indeterminate")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class ConversationOwner(Base):
    __tablename__ = "conversation_owners"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("thread_id", name="uq_conversation_owners_thread"),
        _org_fk(["thread_id"], "inbox_threads", "fk_conversation_owners_org_thread"),
        _org_fk(["owner_user_id"], "users", "fk_conversation_owners_org_user"),
        CheckConstraint(f"state IN ({_in(STATES)})", name="state"),
        CheckConstraint(f"owner_type IN ({_in(OWNER_TYPES)})", name="owner_type"),
        CheckConstraint("(owner_type = 'human') = (owner_user_id IS NOT NULL)", name="human_owner_named"),
        CheckConstraint(
            "(state = 'human_owned' AND owner_type = 'human') OR (state = 'agent_owned' AND owner_type = 'agent')"
            " OR state IN ('new', 'paused', 'blocked', 'resolved')",
            name="state_matches_owner",
        ),
        CheckConstraint("owner_generation >= 0 AND revision >= 1", name="counters"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    thread_id: Mapped[uuid.UUID]
    state: Mapped[str] = mapped_column(String(16))
    owner_type: Mapped[str] = mapped_column(String(8))
    owner_user_id: Mapped[uuid.UUID | None]
    owner_generation: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationOwnerEvent(Base):
    __tablename__ = "conversation_owner_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_conversation_owner_events_idempotency"),
        _org_fk(["thread_id"], "inbox_threads", "fk_conversation_owner_events_org_thread"),
        CheckConstraint(f"command IN ({_in(COMMANDS)})", name="command"),
        CheckConstraint(f"reason IN ({_in(REASONS)})", name="reason"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint("char_length(note) <= 300", name="note_length"),
        Index("ix_conversation_owner_events_thread", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    thread_id: Mapped[uuid.UUID]
    command: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(String(300))
    from_state: Mapped[str] = mapped_column(String(16))
    to_state: Mapped[str] = mapped_column(String(16))
    from_owner: Mapped[str | None] = mapped_column(String(64))
    to_owner: Mapped[str | None] = mapped_column(String(64))
    generation_after: Mapped[int] = mapped_column(Integer)
    revision_after: Mapped[int] = mapped_column(Integer)
    canceled_attempts: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    correlation_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HandoffTask(Base):
    __tablename__ = "handoff_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        _org_fk(["thread_id"], "inbox_threads", "fk_handoff_tasks_org_thread"),
        _org_fk(["assigned_to"], "users", "fk_handoff_tasks_org_user"),
        CheckConstraint("kind = 'handoff'", name="kind"),
        CheckConstraint(f"reason IN ({_in(REASONS)})", name="reason"),
        CheckConstraint("urgency IN ('normal', 'high')", name="urgency"),
        CheckConstraint("status IN ('open', 'acknowledged', 'closed')", name="status"),
        CheckConstraint("context_ref ~ '^(thread|inbound|proposal):[0-9a-f-]{36}$'", name="context_ref_format"),
        Index(
            "uq_handoff_tasks_active",
            "thread_id",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('open', 'acknowledged')"),
        ),  # fmt: skip
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    thread_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(32))
    urgency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    assigned_to: Mapped[uuid.UUID | None]
    context_ref: Mapped[str] = mapped_column(String(60))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class DispatchAttempt(Base):
    __tablename__ = "dispatch_attempts"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_dispatch_attempts_idempotency"),
        _org_fk(["thread_id"], "inbox_threads", "fk_dispatch_attempts_org_thread"),
        _org_fk(["reply_proposal_id"], "reply_proposals", "fk_dispatch_attempts_org_proposal"),
        _org_fk(["contact_id"], "contacts", "fk_dispatch_attempts_org_contact"),
        _org_fk(["provider_connection_id"], "provider_connections", "fk_dispatch_attempts_org_connection"),
        CheckConstraint(f"state IN ({_in(ATTEMPT_STATES)})", name="state"),
        CheckConstraint("transport = 'simulation'", name="simulation_only"),  # no real send path exists (P6.3)
        CheckConstraint("purpose IN ('marketing', 'utility', 'service_reply')", name="purpose"),
        Index("ix_dispatch_attempts_thread_state", "thread_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    thread_id: Mapped[uuid.UUID]
    reply_proposal_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID]
    provider_connection_id: Mapped[uuid.UUID]
    purpose: Mapped[str] = mapped_column(String(16))
    owner_generation: Mapped[int] = mapped_column(Integer)  # the generation it was queued under
    transport: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    deny_reason: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
