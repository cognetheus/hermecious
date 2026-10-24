"""Evidence quality evaluation (P3.4, ADR-019).

`evidence_eval_runs`: one frozen sample of ≤30 distinct accounts, with its seed, fingerprint and result.
`evidence_eval_items`: one row per displayed factual claim at freeze time. Rights-safe summaries only: no excerpts.
`evidence_eval_verdicts`: append-only human verdict revisions.
`evidence_eval_remediations`: append-only links from a failed item to the P1.4 correction that withdrew it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

VERDICTS = ("supported", "unsupported", "contradicted", "stale", "unverifiable")
RESULTS = ("PASSED", "FAILED", "BLOCKED", "INCOMPLETE")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class EvidenceEvalRun(Base):
    __tablename__ = "evidence_eval_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_eval_runs_idempotency"),
        ForeignKeyConstraint(
            ["organization_id", "baseline_run_id"],
            ["evidence_eval_runs.organization_id", "evidence_eval_runs.id"],
            name="fk_eval_runs_org_baseline",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"], ["users.organization_id", "users.id"], name="fk_eval_runs_org_creator"
        ),
        CheckConstraint("kind IN ('baseline', 'post_remediation')", name="kind"),
        CheckConstraint("(kind = 'post_remediation') = (baseline_run_id IS NOT NULL)", name="baseline_link"),
        CheckConstraint("corpus_status IN ('OK', 'INSUFFICIENT_CORPUS', 'SYNTHETIC_CORPUS')", name="corpus_status"),
        CheckConstraint(f"result IS NULL OR result IN ({_in(RESULTS)})", name="result"),
        CheckConstraint("jsonb_array_length(account_ids) <= 30", name="account_bound"),
        CheckConstraint("corpus_fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint_format"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(24))
    baseline_run_id: Mapped[uuid.UUID | None]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    selection_method: Mapped[str] = mapped_column(String(80))
    seed: Mapped[str] = mapped_column(String(64))
    account_ids: Mapped[list[str]] = mapped_column(JSONB)
    excluded_accounts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    corpus_fingerprint: Mapped[str] = mapped_column(String(64))
    corpus_status: Mapped[str] = mapped_column(String(24))
    real_accounts: Mapped[int] = mapped_column(Integer)
    synthetic_accounts: Mapped[int] = mapped_column(Integer)
    numerator: Mapped[int | None] = mapped_column(Integer)
    denominator: Mapped[int | None] = mapped_column(Integer)
    still_displayed_failures: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(16))
    result_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[uuid.UUID | None]
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceEvalItem(Base):
    __tablename__ = "evidence_eval_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "run_id", "item_kind", "ref", name="uq_eval_items_ref"),
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["evidence_eval_runs.organization_id", "evidence_eval_runs.id"],
            name="fk_eval_items_org_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "account_id"],
            ["accounts.organization_id", "accounts.id"],
            name="fk_eval_items_org_account",
        ),
        CheckConstraint("item_kind IN ('fact', 'signal', 'dimension')", name="item_kind"),
        CheckConstraint(f"verdict IS NULL OR verdict IN ({_in(VERDICTS)})", name="verdict"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    item_kind: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str] = mapped_column(String(200))
    display_text: Mapped[str] = mapped_column(Text)
    fact_ids: Mapped[list[str]] = mapped_column(JSONB)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    real_provenance: Mapped[bool] = mapped_column(Boolean)
    eligibility_at_freeze: Mapped[str] = mapped_column(String(24))
    verdict: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer)


class EvidenceEvalVerdict(Base):
    """Append-only (trigger)."""

    __tablename__ = "evidence_eval_verdicts"
    __table_args__ = (
        UniqueConstraint("organization_id", "item_id", "revision", name="uq_eval_verdicts_revision"),
        ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["evidence_eval_items.organization_id", "evidence_eval_items.id"],
            name="fk_eval_verdicts_org_item",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_id"],
            ["users.organization_id", "users.id"],
            name="fk_eval_verdicts_org_reviewer",
        ),
        CheckConstraint(f"verdict IN ({_in(VERDICTS)})", name="verdict"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 1000", name="reason_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    item_id: Mapped[uuid.UUID]
    revision: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceEvalRemediation(Base):
    """Append-only (trigger): which P1.4 correction withdrew a failed displayed fact."""

    __tablename__ = "evidence_eval_remediations"
    __table_args__ = (
        UniqueConstraint("organization_id", "item_id", name="uq_eval_remediations_item"),
        ForeignKeyConstraint(
            ["organization_id", "item_id"],
            ["evidence_eval_items.organization_id", "evidence_eval_items.id"],
            name="fk_eval_remediations_org_item",
        ),
        ForeignKeyConstraint(
            ["organization_id", "correction_fact_id"],
            ["account_facts.organization_id", "account_facts.id"],
            name="fk_eval_remediations_org_fact",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_eval_remediations_org_creator",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    item_id: Mapped[uuid.UUID]
    correction_fact_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
