"""Contract: every /api/v1 route except the public allowlist requires a session."""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import RouteContext, iter_route_contexts
from fastapi.testclient import TestClient

from app.auth.dependencies import PUBLIC_API_PATHS, assert_api_routes_protected
from app.main import create_app
from tests.factories import TEST_ORIGIN, make_settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings(), readiness_checks={})


def api_routes(app: FastAPI) -> list[RouteContext]:
    return [r for r in iter_route_contexts(app.routes) if (r.path or "").startswith("/api/v1")]


def test_public_allowlist_is_exactly_login_and_the_signed_webhook(app: FastAPI) -> None:
    # The Meta webhook (P5.2, ADR-027) has no session; it is authenticated by HMAC (POST) and verify token (GET).
    assert frozenset({"/api/v1/auth/login", "/api/v1/integrations/whatsapp/webhook"}) == PUBLIC_API_PATHS
    assert {r.path for r in api_routes(app)} >= {"/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout"}


def test_every_private_route_rejects_anonymous_callers(app: FastAPI) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    checked = 0
    for route in api_routes(app):
        if route.path in PUBLIC_API_PATHS:
            continue
        for method in route.methods or set():
            assert route.path is not None
            response = client.request(method, route.path, headers={"Origin": TEST_ORIGIN})
            assert response.status_code == 401, (method, route.path)
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"
            checked += 1
    assert checked >= 3


def test_startup_refuses_an_unprotected_api_route(app: FastAPI) -> None:
    leaky = APIRouter(prefix="/api/v1/leaky")

    @leaky.get("/data")
    def data() -> dict[str, str]:
        return {"secret": "data"}

    app.include_router(leaky)
    with pytest.raises(RuntimeError, match="/api/v1/leaky/data"):
        assert_api_routes_protected(app)


def test_no_interactive_docs_or_schema_are_exposed(app: FastAPI) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
