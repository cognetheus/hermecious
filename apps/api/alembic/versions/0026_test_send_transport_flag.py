"""Record whether a P5.3 test send used the real Graph client (P5.5 audit fix).

Readiness counts only real sends as WATEST-10 evidence. Existing rows are marked simulated: unknown is never real.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_test_sends",
        sa.Column("simulated_transport", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("provider_test_sends", "simulated_transport")
