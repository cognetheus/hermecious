"""Provider connection binding (P5.1, ADR-026). Owner-only; no outbound capability lives here."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.core.settings import Settings
from app.whatsapp.contracts import ProviderConnectionView, ProviderEnvironment
from app.whatsapp.models import ProviderConnection

PROVIDER = "meta_whatsapp"
CREDENTIAL_REF = "env:HERMECIOUS_WHATSAPP_ACCESS_TOKEN"


def view(row: ProviderConnection) -> ProviderConnectionView:
    return ProviderConnectionView(
        connection_id=row.id,
        organization_id=row.organization_id,
        waba_id=row.waba_id,
        phone_number_id=row.phone_number_id,
        graph_version=row.graph_version,
        mode=ProviderEnvironment(row.mode),
        enabled=row.enabled,
        credential_ref=row.credential_ref,
    )


def bind_connection(db: Session, *, actor: Actor, clock: Clock, settings: Settings) -> ProviderConnectionView:
    """Bind this organization to the *configured* WABA and phone-number ID (never IDs from a request)."""
    account_service._require(actor, Capability.ADMINISTER)
    if settings.whatsapp_mode == "simulation":
        raise InvalidRequest("simulation mode has no provider connection")
    waba, phone = settings.whatsapp_waba_id, settings.whatsapp_phone_number_id
    if not waba or not phone:
        raise InvalidRequest("no WhatsApp Business Account or phone-number ID is configured")
    taken = db.scalar(
        select(ProviderConnection)
        .where(ProviderConnection.provider == PROVIDER, ProviderConnection.phone_number_id == phone)
        .with_for_update()
    )
    now = clock.now()
    if taken is not None and taken.organization_id != actor.organization_id:
        raise Conflict("this phone-number ID is bound to another organization")
    if taken is None:
        taken = ProviderConnection(
            organization_id=actor.organization_id, provider=PROVIDER, waba_id=waba, phone_number_id=phone,
            graph_version=settings.whatsapp_graph_version, mode=settings.whatsapp_mode, enabled=True,
            credential_ref=CREDENTIAL_REF, created_by=actor.user_id, created_at=now, updated_at=now, version=1,
        )  # fmt: skip
        db.add(taken)
    elif (taken.waba_id, taken.graph_version, taken.mode) != (
        waba,
        settings.whatsapp_graph_version,
        settings.whatsapp_mode,
    ):
        taken.waba_id, taken.graph_version, taken.mode = waba, settings.whatsapp_graph_version, settings.whatsapp_mode
        taken.updated_at, taken.version = now, taken.version + 1
    db.flush()
    management._audit(db, actor, clock, "whatsapp.connection_bound", taken.id,
                      {"mode": taken.mode, "graph_version": taken.graph_version, "version": taken.version},
                      target_type="provider_connection")  # fmt: skip
    db.commit()
    return view(taken)


def connection_for(db: Session, org: uuid.UUID, settings: Settings) -> ProviderConnectionView:
    """This organization's enabled connection, only if it is exactly the configured one (no credential fallthrough)."""
    row = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.organization_id == org, ProviderConnection.provider == PROVIDER
        )
    )
    if row is None:
        raise NotFound()
    if (row.waba_id, row.phone_number_id, row.mode) != (
        settings.whatsapp_waba_id,
        settings.whatsapp_phone_number_id,
        settings.whatsapp_mode,
    ):
        raise Forbidden("this organization's connection does not match the configured WhatsApp credentials")
    return view(row)
