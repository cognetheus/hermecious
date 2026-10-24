"""Durable jobs, transactional outbox, account audit snapshots (P1.5, ADR-011).

PostgreSQL is the only authority for jobs and events. `account_audit_snapshots`
is the first DB-only job effect, idempotent per job via UNIQUE(organization_id, job_id).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ERROR_CLASS = "last_error_class IS NULL OR last_error_class ~ '^[a-z][a-z0-9_]{1,63}$'"
TYPE_FORMAT = "~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'"
KEY_FORMAT = "idempotency_key ~ '^[A-Za-z0-9._:-]{1,200}$'"


def _ts(name: str, nullable: bool = False) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(80), nullable=False),
        sa.Column("job_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        _ts("available_at"),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        _ts("lease_expires_at", nullable=True),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("last_error_class", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("result_digest", sa.String(64), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retry_wait', 'succeeded', 'dead', 'cancelled')",
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint(f"job_type {TYPE_FORMAT}", name=op.f("ck_jobs_job_type_format")),
        sa.CheckConstraint(KEY_FORMAT, name=op.f("ck_jobs_idempotency_key_format")),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 10", name=op.f("ck_jobs_max_attempts_range")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_jobs_attempts_non_negative")),
        sa.CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_jobs_payload_digest_format")),
        sa.CheckConstraint(
            "status <> 'running'"
            " OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_jobs_running_has_lease"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'dead', 'cancelled') OR finished_at IS NOT NULL",
            name=op.f("ck_jobs_terminal_has_finish"),
        ),
        sa.CheckConstraint(ERROR_CLASS, name=op.f("ck_jobs_error_class_format")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_jobs_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint(
            "organization_id",
            "job_type",
            "idempotency_key",
            name=op.f("uq_jobs_organization_id_job_type_idempotency_key"),
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_jobs_organization_id_id")),
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["status", "available_at", "lease_expires_at", "id"],
        postgresql_where=sa.text("status IN ('pending', 'retry_wait', 'running')"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.String(40), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        _ts("dispatched_at", nullable=True),
        sa.Column("dispatch_sink", sa.String(16), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        _ts("next_attempt_at"),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        _ts("lease_expires_at", nullable=True),
        sa.Column("last_error_class", sa.String(64), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(f"event_type {TYPE_FORMAT}", name=op.f("ck_outbox_events_event_type_format")),
        sa.CheckConstraint(
            "aggregate_type ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_outbox_events_aggregate_type_format")
        ),
        sa.CheckConstraint(KEY_FORMAT, name=op.f("ck_outbox_events_idempotency_key_format")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_outbox_events_attempts_non_negative")),
        sa.CheckConstraint(
            "(dispatched_at IS NULL) = (dispatch_sink IS NULL)", name=op.f("ck_outbox_events_dispatch_has_sink")
        ),
        sa.CheckConstraint(
            "dispatch_sink IS NULL OR dispatch_sink IN ('redis', 'none')",
            name=op.f("ck_outbox_events_dispatch_sink_values"),
        ),
        sa.CheckConstraint(ERROR_CLASS, name=op.f("ck_outbox_events_error_class_format")),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name=op.f("fk_outbox_events_organization_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint(
            "organization_id",
            "event_type",
            "idempotency_key",
            name=op.f("uq_outbox_events_organization_id_event_type_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_outbox_events_undispatched",
        "outbox_events",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    op.create_table(
        "account_audit_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("account_version", sa.Integer(), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("current_fact_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_digest", sa.String(64), nullable=False),
        _ts("taken_at"),
        sa.CheckConstraint(
            "snapshot_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_account_audit_snapshots_snapshot_digest_format")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_account_audit_snapshots_org_account",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["jobs.organization_id", "jobs.id"],
            name="fk_account_audit_snapshots_org_job",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_account_audit_snapshots_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_audit_snapshots")),
        sa.UniqueConstraint(
            "organization_id", "job_id", name=op.f("uq_account_audit_snapshots_organization_id_job_id")
        ),
    )


def downgrade() -> None:
    # Pending/dead jobs and undispatched events are durable work and history: on
    # data-bearing databases drain or export them first; never drop pending work silently.
    op.drop_table("account_audit_snapshots")
    op.drop_index("ix_outbox_events_undispatched", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_table("jobs")
