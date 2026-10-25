"""Audit fixes: claim uniqueness per rule, newest-only brief dedupe, frozen dry-run pool, proof hint.

- research_claims: one claim per (observation, type, rule, span); two rules on one sentence no longer collide.
- school_signal_snapshots: no uniqueness on the input digest; generation compares with the newest brief only.
- simulation_runs.account_ids: the candidate pool, frozen at the first attempt so retries converge.
- contact_permissions.proof_hint: the last four characters of the proof reference, so the reviewing owner knows
  which record to check (the reference itself stays a keyed digest). Immutable like the rest of the evidence.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVIDENCE = (
    "id, organization_id, contact_id, channel, purpose, business_name, basis, capture_method,"
    " consent_wording_version, proof_kind, proof_key_id, proof_digest, captured_at, recorded_at, expires_at,"
    " recorded_by, supersedes_id"
)


def _row(prefix: str, columns: str) -> str:
    return "ROW(" + ", ".join(f"{prefix}.{c.strip()}" for c in columns.split(",")) + ")"


def _guard(columns: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION hermecious_contact_permission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'contact permission evidence is history and is never deleted';
            END IF;
            IF {_row("NEW", columns)} IS DISTINCT FROM {_row("OLD", columns)} THEN
                RAISE EXCEPTION 'contact permission evidence is immutable';
            END IF;
            IF NOT ((OLD.status = 'pending' AND NEW.status IN ('verified', 'rejected', 'revoked', 'superseded'))
                    OR (OLD.status = 'verified' AND NEW.status IN ('revoked', 'superseded'))) THEN
                RAISE EXCEPTION 'invalid contact permission transition % -> %', OLD.status, NEW.status;
            END IF;
            IF OLD.reviewed_by IS NOT NULL AND ROW(NEW.reviewed_by, NEW.reviewed_at, NEW.review_reason,
                    NEW.effective_at) IS DISTINCT FROM ROW(OLD.reviewed_by, OLD.reviewed_at, OLD.review_reason,
                    OLD.effective_at) THEN
                RAISE EXCEPTION 'a contact permission review is recorded once';
            END IF;
            IF NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'contact permission version must increase by one';
            END IF;
            RETURN NEW;
        END
        $$
    """


def upgrade() -> None:
    op.drop_constraint("uq_research_claims_span", "research_claims", type_="unique")
    op.create_unique_constraint(
        "uq_research_claims_span_rule",
        "research_claims",
        ["organization_id", "observation_id", "claim_type", "rule_id", "locator_start", "locator_end"],
    )
    op.drop_constraint("uq_signal_snapshots_input", "school_signal_snapshots", type_="unique")
    op.add_column("simulation_runs", sa.Column("account_ids", postgresql.JSONB(), nullable=True))
    op.add_column("contact_permissions", sa.Column("proof_hint", sa.String(16), server_default="", nullable=False))
    op.execute(_guard(_EVIDENCE + ", proof_hint"))


def downgrade() -> None:
    op.execute(_guard(_EVIDENCE))
    op.drop_column("contact_permissions", "proof_hint")
    op.drop_column("simulation_runs", "account_ids")
    op.create_unique_constraint(
        "uq_signal_snapshots_input",
        "school_signal_snapshots",
        ["organization_id", "account_id", "rubric_version", "input_digest"],
    )
    op.drop_constraint("uq_research_claims_span_rule", "research_claims", type_="unique")
    op.create_unique_constraint(
        "uq_research_claims_span",
        "research_claims",
        ["organization_id", "observation_id", "claim_type", "locator_start", "locator_end"],
    )
