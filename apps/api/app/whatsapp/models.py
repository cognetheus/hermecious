"""Provider connections (P5.1, ADR-026): which organization owns which Meta WABA and phone-number ID.

A phone-number ID belongs to exactly one organization. The row stores identifiers and the *name* of the secret
source (`credential_ref`); secrets stay in the environment.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("provider", "phone_number_id", name="uq_provider_connections_phone"),
        UniqueConstraint("organization_id", "provider", name="uq_provider_connections_org"),  # one per org (Batch 08)
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["users.organization_id", "users.id"],
            name="fk_provider_connections_org_creator",
        ),
        CheckConstraint("provider = 'meta_whatsapp'", name="provider"),
        CheckConstraint("mode IN ('contract_test', 'provider_test', 'production')", name="mode"),
        CheckConstraint("waba_id ~ '^[0-9]{5,20}$' AND phone_number_id ~ '^[0-9]{5,20}$'", name="meta_ids"),
        CheckConstraint("graph_version ~ '^v[0-9]{2}\\.0$'", name="graph_version"),
        CheckConstraint("credential_ref LIKE 'env:%'", name="credential_ref"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(String(32))
    waba_id: Mapped[str] = mapped_column(String(20))
    phone_number_id: Mapped[str] = mapped_column(String(20))
    graph_version: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean)
    credential_ref: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
