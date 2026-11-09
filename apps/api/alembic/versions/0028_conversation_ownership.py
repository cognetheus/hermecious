"""Conversation ownership, append-only owner events, handoff tasks and fenced dispatch attempts (P6.3).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATES = "'new', 'agent_owned', 'human_owned', 'paused', 'blocked', 'resolved'"
COMMANDS = ("'takeover', 'assign', 'pause', 'block', 'resolve', 'release_to_agent', 'reopen', 'open_handoff',"
            " 'acknowledge_handoff'")  # fmt: skip
REASONS = ("'human_requested', 'unknown_offer', 'sensitive', 'conflicting_facts', 'operator_takeover', 'manual',"
           " 'unmatched_contact', 'quality_concern', 'resolved_by_operator', 'agent_release_approved'")  # fmt: skip
ATTEMPTS = "'queued', 'denied', 'canceled', 'submitting', 'accepted', 'rejected', 'indeterminate'"


def _fk(cols: list[str], target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


def _base(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("organization_id", "id", name=op.f(f"uq_{table}_organization_id_id")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f(f"fk_{table}_organization_id_organizations")
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "conversation_owners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("owner_type", sa.String(8), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_generation", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"state IN ({STATES})", name=op.f("ck_conversation_owners_state")),
        sa.CheckConstraint("owner_type IN ('none', 'agent', 'human')", name=op.f("ck_conversation_owners_owner_type")),
        sa.CheckConstraint(
            "(owner_type = 'human') = (owner_user_id IS NOT NULL)",
            name=op.f("ck_conversation_owners_human_owner_named"),
        ),
        sa.CheckConstraint(
            "(state = 'human_owned' AND owner_type = 'human') OR (state = 'agent_owned' AND owner_type = 'agent')"
            " OR state IN ('new', 'paused', 'blocked', 'resolved')",
            name=op.f("ck_conversation_owners_state_matches_owner"),
        ),
        sa.CheckConstraint("owner_generation >= 0 AND revision >= 1", name=op.f("ck_conversation_owners_counters")),
        _fk(["thread_id"], "inbox_threads", "fk_conversation_owners_org_thread"),
        _fk(["owner_user_id"], "users", "fk_conversation_owners_org_user"),
        sa.UniqueConstraint("thread_id", name="uq_conversation_owners_thread"),
        *_base("conversation_owners"),
    )
    op.create_table(
        "conversation_owner_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("command", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        sa.Column("from_state", sa.String(16), nullable=False),
        sa.Column("to_state", sa.String(16), nullable=False),
        sa.Column("from_owner", sa.String(64), nullable=True),
        sa.Column("to_owner", sa.String(64), nullable=True),
        sa.Column("generation_after", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("canceled_attempts", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(80), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"command IN ({COMMANDS})", name=op.f("ck_conversation_owner_events_command")),
        sa.CheckConstraint(f"reason IN ({REASONS})", name=op.f("ck_conversation_owner_events_reason")),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_conversation_owner_events_request_digest_format")
        ),
        sa.CheckConstraint("char_length(note) <= 300", name=op.f("ck_conversation_owner_events_note_length")),
        _fk(["thread_id"], "inbox_threads", "fk_conversation_owner_events_org_thread"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_conversation_owner_events_actor_id_users")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_conversation_owner_events_idempotency"),
        *_base("conversation_owner_events"),
    )
    op.create_index("ix_conversation_owner_events_thread", "conversation_owner_events", ["thread_id", "created_at"])
    op.create_table(
        "handoff_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("urgency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("context_ref", sa.String(60), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind = 'handoff'", name=op.f("ck_handoff_tasks_kind")),
        sa.CheckConstraint(f"reason IN ({REASONS})", name=op.f("ck_handoff_tasks_reason")),
        sa.CheckConstraint("urgency IN ('normal', 'high')", name=op.f("ck_handoff_tasks_urgency")),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'closed')", name=op.f("ck_handoff_tasks_status")),
        sa.CheckConstraint(
            "context_ref ~ '^(thread|inbound|proposal):[0-9a-f-]{36}$'",
            name=op.f("ck_handoff_tasks_context_ref_format"),
        ),
        _fk(["thread_id"], "inbox_threads", "fk_handoff_tasks_org_thread"),
        _fk(["assigned_to"], "users", "fk_handoff_tasks_org_user"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_handoff_tasks_created_by_users")),
        *_base("handoff_tasks"),
    )
    op.create_index(
        "uq_handoff_tasks_active", "handoff_tasks", ["thread_id", "kind"], unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )  # fmt: skip
    op.create_table(
        "dispatch_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("reply_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("provider_connection_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("owner_generation", sa.Integer(), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("deny_reason", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"state IN ({ATTEMPTS})", name=op.f("ck_dispatch_attempts_state")),
        sa.CheckConstraint("transport = 'simulation'", name=op.f("ck_dispatch_attempts_simulation_only")),
        sa.CheckConstraint(
            "purpose IN ('marketing', 'utility', 'service_reply')", name=op.f("ck_dispatch_attempts_purpose")
        ),
        _fk(["thread_id"], "inbox_threads", "fk_dispatch_attempts_org_thread"),
        _fk(["reply_proposal_id"], "reply_proposals", "fk_dispatch_attempts_org_proposal"),
        _fk(["contact_id"], "contacts", "fk_dispatch_attempts_org_contact"),
        _fk(["provider_connection_id"], "provider_connections", "fk_dispatch_attempts_org_connection"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_dispatch_attempts_idempotency"),
        *_base("dispatch_attempts"),
    )
    op.create_index("ix_dispatch_attempts_thread_state", "dispatch_attempts", ["thread_id", "state"])
    op.execute(
        "CREATE TRIGGER conversation_owner_events_append_only BEFORE UPDATE OR DELETE ON conversation_owner_events"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )
    op.execute(
        """
        CREATE FUNCTION hermecious_owner_generation_monotonic() RETURNS trigger AS $$
        BEGIN
            IF NEW.owner_generation < OLD.owner_generation THEN
                RAISE EXCEPTION 'owner_generation may never decrease';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER conversation_owners_generation_monotonic BEFORE UPDATE ON conversation_owners"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_owner_generation_monotonic()"
    )
    op.execute(
        "CREATE TRIGGER conversation_owners_no_delete BEFORE DELETE ON conversation_owners"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    # Ownership history and dispatch attempts are audit evidence: export first on data-bearing databases.
    op.execute("DROP TRIGGER conversation_owners_no_delete ON conversation_owners")
    op.execute("DROP TRIGGER conversation_owners_generation_monotonic ON conversation_owners")
    op.execute("DROP FUNCTION hermecious_owner_generation_monotonic()")
    op.execute("DROP TRIGGER conversation_owner_events_append_only ON conversation_owner_events")
    op.drop_index("ix_dispatch_attempts_thread_state", table_name="dispatch_attempts")
    op.drop_table("dispatch_attempts")
    op.drop_index("uq_handoff_tasks_active", table_name="handoff_tasks")
    op.drop_table("handoff_tasks")
    op.drop_index("ix_conversation_owner_events_thread", table_name="conversation_owner_events")
    op.drop_table("conversation_owner_events")
    op.drop_table("conversation_owners")
