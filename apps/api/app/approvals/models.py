"""Append-only content reviews of draft revisions (P4.4, ADR-023).

A review row is the immutable receipt of one decision on one exact draft revision (by content digest):
`approved_content`, `rejected` or `revoked`. Rows are never updated; the current approval status is computed
from the latest row plus live dependency checks. Every row is `simulation_only`.
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


def _org_fk(cols: list[str], target: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["organization_id", *cols], [f"{target}.organization_id", f"{target}.id"], name=name)


class DraftReview(Base):
    __tablename__ = "draft_reviews"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "draft_id", "seq", name="uq_draft_reviews_seq"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_draft_reviews_idempotency"),
        _org_fk(["draft_id"], "drafts", "fk_draft_reviews_org_draft"),
        _org_fk(["campaign_id"], "campaigns", "fk_draft_reviews_org_campaign"),
        _org_fk(["account_id"], "accounts", "fk_draft_reviews_org_account"),
        _org_fk(["contact_id"], "contacts", "fk_draft_reviews_org_contact"),
        _org_fk(["reviewer_id"], "users", "fk_draft_reviews_org_reviewer"),
        _org_fk(["revokes_id"], "draft_reviews", "fk_draft_reviews_org_revokes"),
        CheckConstraint("decision IN ('approved_content', 'rejected', 'revoked')", name="decision"),
        CheckConstraint("simulation_only", name="simulation_only"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="content_digest_format"),
        CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="request_digest_format"),
        CheckConstraint("char_length(reason) BETWEEN 3 AND 500", name="reason_length"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint(
            "decision <> 'approved_content' OR (contact_id IS NOT NULL AND purpose IS NOT NULL"
            " AND template_ref IS NOT NULL AND expires_at IS NOT NULL"
            " AND eligibility_decision IN ('allow_for_simulation', 'defer'))",
            name="approval_binding",
        ),
        CheckConstraint("(decision = 'revoked') = (revokes_id IS NOT NULL)", name="revocation_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    draft_id: Mapped[uuid.UUID]
    campaign_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    draft_revision: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20))
    content_digest: Mapped[str] = mapped_column(String(64))
    contact_id: Mapped[uuid.UUID | None]
    purpose: Mapped[str | None] = mapped_column(String(16))
    template_ref: Mapped[str | None] = mapped_column(String(80))
    eligibility_decision: Mapped[str | None] = mapped_column(String(24))
    simulation_only: Mapped[bool] = mapped_column(Boolean)
    version_vector: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID]
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revokes_id: Mapped[uuid.UUID | None]
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_digest: Mapped[str] = mapped_column(String(64))
