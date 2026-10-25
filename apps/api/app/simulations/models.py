"""Simulation runs and items (P4.5, ADR-024): a separate namespace that never touches real message state.

A run evaluates up to 30 campaign candidates once, with fresh P4.3/P4.4 checks per item. Items are append-only and
unique per (run, account), so a crashed worker that retries converges on one logical result per account. Simulated
receipt ids always start with `sim-`; there are no provider ids.
"""

import uuid
from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

SCENARIOS = (
    "all_allow",
    "opt_out_mid_run",
    "quiet_hours",
    "quota",
    "stale_approval",
    "provider_429_mock",
    "transport_timeout_mock",
    "worker_restart_mock",
)
RUN_STATUSES = ("pending", "running", "completed", "cancelled", "failed")
BUCKETS = ("accepted", "denied", "deferred", "invalid")
LIFECYCLES = ("sim_delivered", "sim_failed", "not_attempted")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_simulation_runs_idempotency"),
        _org_fk(["campaign_id"], "campaigns", "fk_simulation_runs_org_campaign"),
        _org_fk(["requested_by"], "users", "fk_simulation_runs_org_requester"),
        CheckConstraint(f"scenario IN ({_in(SCENARIOS)})", name="scenario"),
        CheckConstraint(f"status IN ({_in(RUN_STATUSES)})", name="status"),
        CheckConstraint("mode IN ('fixture', 'readiness')", name="mode"),
        CheckConstraint("max_items BETWEEN 1 AND 30", name="max_items"),
        CheckConstraint("considered >= 0 AND considered <= max_items", name="considered"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint("report_digest IS NULL OR report_digest ~ '^[0-9a-f]{64}$'", name="report_digest_format"),
        CheckConstraint("real_messages_sent = 0", name="zero_real_messages"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "uq_simulation_runs_one_active",
            "organization_id",
            "campaign_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    campaign_id: Mapped[uuid.UUID]
    scenario: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    max_items: Mapped[int] = mapped_column(Integer)
    considered: Mapped[int] = mapped_column(Integer)
    account_ids: Mapped[list[str] | None] = mapped_column(JSONB)  # candidate pool, frozen at the first attempt
    real_messages_sent: Mapped[int] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String(40))
    simulator_version: Mapped[str] = mapped_column(String(40))
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_digest: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID]
    requested_cancel_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)


class SimulationItem(Base):
    __tablename__ = "simulation_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "account_id", name="uq_simulation_items_account"),
        UniqueConstraint("organization_id", "run_id", "seq", name="uq_simulation_items_seq"),
        _org_fk(["run_id"], "simulation_runs", "fk_simulation_items_org_run"),
        _org_fk(["account_id"], "accounts", "fk_simulation_items_org_account"),
        _org_fk(["contact_id"], "contacts", "fk_simulation_items_org_contact"),
        _org_fk(["draft_id"], "drafts", "fk_simulation_items_org_draft"),
        _org_fk(["approval_id"], "draft_reviews", "fk_simulation_items_org_approval"),
        CheckConstraint(f"bucket IN ({_in(BUCKETS)})", name="bucket"),
        CheckConstraint(f"lifecycle IN ({_in(LIFECYCLES)})", name="lifecycle"),
        CheckConstraint("(bucket = 'accepted') = (lifecycle <> 'not_attempted')", name="lifecycle_only_when_accepted"),
        CheckConstraint(
            "(lifecycle = 'sim_delivered') = (sim_receipt_id IS NOT NULL)", name="receipt_only_when_delivered"
        ),
        CheckConstraint("sim_receipt_id IS NULL OR sim_receipt_id ~ '^sim-[0-9a-f]{24}$'", name="sim_receipt_format"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts_bounded"),
        CheckConstraint("seq >= 1", name="seq_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID | None]
    draft_id: Mapped[uuid.UUID | None]
    draft_revision: Mapped[int | None] = mapped_column(Integer)
    content_digest: Mapped[str | None] = mapped_column(String(64))
    approval_id: Mapped[uuid.UUID | None]
    bucket: Mapped[str] = mapped_column(String(16))
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    lifecycle: Mapped[str] = mapped_column(String(16))
    sim_receipt_id: Mapped[str | None] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer)
    next_window_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permission_revision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(40))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
