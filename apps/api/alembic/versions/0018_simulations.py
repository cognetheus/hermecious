"""Zero-egress dry runs: simulation_runs, simulation_items (P4.5).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCENARIOS = (
    "'all_allow', 'opt_out_mid_run', 'quiet_hours', 'quota', 'stale_approval', 'provider_429_mock',"
    " 'transport_timeout_mock', 'worker_restart_mock'"
)


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
        "simulation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("max_items", sa.Integer(), nullable=False),
        sa.Column("considered", sa.Integer(), nullable=False),
        sa.Column("real_messages_sent", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("simulator_version", sa.String(40), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=True),
        sa.Column("report_digest", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"scenario IN ({SCENARIOS})", name=op.f("ck_simulation_runs_scenario")),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'cancelled', 'failed')",
            name=op.f("ck_simulation_runs_status"),
        ),
        sa.CheckConstraint("mode IN ('fixture', 'readiness')", name=op.f("ck_simulation_runs_mode")),
        sa.CheckConstraint("max_items BETWEEN 1 AND 30", name=op.f("ck_simulation_runs_max_items")),
        sa.CheckConstraint("considered >= 0 AND considered <= max_items", name=op.f("ck_simulation_runs_considered")),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_simulation_runs_request_digest_format")),
        sa.CheckConstraint(
            "report_digest IS NULL OR report_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_simulation_runs_report_digest_format"),
        ),
        sa.CheckConstraint("real_messages_sent = 0", name=op.f("ck_simulation_runs_zero_real_messages")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_simulation_runs_version_positive")),
        _fk(["campaign_id"], "campaigns", "fk_simulation_runs_org_campaign"),
        _fk(["requested_by"], "users", "fk_simulation_runs_org_requester"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_simulation_runs_idempotency"),
        *_base("simulation_runs"),
    )
    op.create_index(
        "uq_simulation_runs_one_active",
        "simulation_runs",
        ["organization_id", "campaign_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_table(
        "simulation_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=True),
        sa.Column("content_digest", sa.String(64), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("sim_receipt_id", sa.String(32), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_window_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permission_revision", postgresql.JSONB(), nullable=True),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "bucket IN ('accepted', 'denied', 'deferred', 'invalid')", name=op.f("ck_simulation_items_bucket")
        ),
        sa.CheckConstraint(
            "lifecycle IN ('sim_delivered', 'sim_failed', 'not_attempted')",
            name=op.f("ck_simulation_items_lifecycle"),
        ),
        sa.CheckConstraint(
            "(bucket = 'accepted') = (lifecycle <> 'not_attempted')",
            name=op.f("ck_simulation_items_lifecycle_only_when_accepted"),
        ),
        sa.CheckConstraint(
            "(lifecycle = 'sim_delivered') = (sim_receipt_id IS NOT NULL)",
            name=op.f("ck_simulation_items_receipt_only_when_delivered"),
        ),
        sa.CheckConstraint(
            "sim_receipt_id IS NULL OR sim_receipt_id ~ '^sim-[0-9a-f]{24}$'",
            name=op.f("ck_simulation_items_sim_receipt_format"),
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name=op.f("ck_simulation_items_attempts_bounded")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_simulation_items_seq_positive")),
        _fk(["run_id"], "simulation_runs", "fk_simulation_items_org_run"),
        _fk(["account_id"], "accounts", "fk_simulation_items_org_account"),
        _fk(["contact_id"], "contacts", "fk_simulation_items_org_contact"),
        _fk(["draft_id"], "drafts", "fk_simulation_items_org_draft"),
        _fk(["approval_id"], "draft_reviews", "fk_simulation_items_org_approval"),
        sa.UniqueConstraint("organization_id", "run_id", "account_id", name="uq_simulation_items_account"),
        sa.UniqueConstraint("organization_id", "run_id", "seq", name="uq_simulation_items_seq"),
        *_base("simulation_items"),
    )
    op.execute(
        "CREATE TRIGGER simulation_items_append_only BEFORE UPDATE OR DELETE ON simulation_items"
        " FOR EACH ROW EXECUTE FUNCTION hermecious_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER simulation_items_append_only ON simulation_items")
    op.drop_table("simulation_items")
    op.drop_index("uq_simulation_runs_one_active", table_name="simulation_runs")
    op.drop_table("simulation_runs")
