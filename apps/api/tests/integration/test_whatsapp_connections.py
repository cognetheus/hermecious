"""P5.1 WAAD-09: provider connections are bound to one organization; no credential fallthrough. No network."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth.models import Role
from app.auth.service import Actor
from app.core.errors import Conflict, Forbidden, NotFound
from app.whatsapp import service, transport
from tests.integration.auth_helpers import add_organization, add_user, db

pytestmark = pytest.mark.usefixtures("app")
NOW = datetime(2026, 10, 29, 7, 0, tzinfo=UTC)


def owner(app: FastAPI, name: str, email: str) -> Actor:
    org = add_organization(app, name)
    user = add_user(app, org, email, role=Role.OWNER)
    return Actor(user_id=user, organization_id=org, role=Role.OWNER, session_id=uuid.uuid4(), verifier="")


def provider_settings(app: FastAPI, phone: str = "200000000000002") -> object:
    return app.state.settings.model_copy(
        update={
            "environment": "development", "whatsapp_mode": "provider_test", "whatsapp_waba_id": "100000000000001",
            "whatsapp_phone_number_id": phone, "whatsapp_test_identity_confirmed_by": "Owner",
            "whatsapp_test_identity_confirmed_at": NOW,
        }
    )  # fmt: skip


def test_waad_09_connections_are_org_bound_and_never_fall_through(app: FastAPI) -> None:
    a, b = owner(app, "Org A", "owner@a.example"), owner(app, "Org B", "owner@b.example")
    settings = provider_settings(app)
    with db(app) as session:
        bound = service.bind_connection(session, actor=a, clock=app.state.clock, settings=settings)  # type: ignore[arg-type]
        assert (bound.organization_id, bound.mode, bound.credential_ref) == (
            a.organization_id,
            "provider_test",
            "env:HERMECIOUS_WHATSAPP_ACCESS_TOKEN",
        )
        again = service.bind_connection(session, actor=a, clock=app.state.clock, settings=settings)  # type: ignore[arg-type]
        assert again.connection_id == bound.connection_id  # idempotent
        with pytest.raises(Conflict):  # one phone-number ID belongs to exactly one organization
            service.bind_connection(session, actor=b, clock=app.state.clock, settings=settings)  # type: ignore[arg-type]
    with db(app) as session:
        with pytest.raises(NotFound):
            service.connection_for(session, b.organization_id, settings)  # type: ignore[arg-type]
        other_phone = provider_settings(app, "200000000000777")
        with pytest.raises(Forbidden):  # configured credentials are for another phone: no fallthrough
            service.connection_for(session, a.organization_id, other_phone)  # type: ignore[arg-type]
        view = service.connection_for(session, a.organization_id, settings)  # type: ignore[arg-type]
    graph_calls: list[str] = []

    class Fake:
        def request_json(self, method: str, url: str, **_kw: object) -> tuple[int, bytes]:
            graph_calls.append(url)
            return 500, b"{}"

    sender = transport.MetaCloudTransport(view, Fake(), lambda: "x", lambda: NOW)
    from tests.unit.test_whatsapp_transport import RECIPIENT_RESOLVED, intent, template  # noqa: PLC0415

    foreign = intent(organization_id=b.organization_id, provider_connection_id=view.connection_id)
    with pytest.raises(transport.ProviderCallError, match="another organization"):
        sender.build_payload(foreign, RECIPIENT_RESOLVED, template())
    assert graph_calls == []
    with db(app) as session, pytest.raises(IntegrityError):  # the database refuses a non-numeric Meta id
        session.execute(text("UPDATE provider_connections SET phone_number_id = '../x'"))
        session.commit()
