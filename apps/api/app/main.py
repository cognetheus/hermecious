from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from redis import Redis

from app.accounts import routes as account_routes
from app.api import health
from app.api.middleware import install_error_handling
from app.approvals import routes as approval_routes
from app.auth import routes as auth_routes
from app.auth.dependencies import assert_api_routes_protected
from app.auth.rate_limit import LoginRateLimiter
from app.campaigns import routes as campaign_routes
from app.contacts import routes as contact_routes
from app.core.clock import Clock, SystemClock
from app.core.settings import Settings
from app.discovery import routes as discovery_routes
from app.drafts import routes as draft_routes
from app.evaluation import routes as evaluation_routes
from app.jobs import routes as job_routes
from app.offers import routes as offer_routes
from app.persistence.db import make_engine, make_session_factory
from app.qualification import routes as qualification_routes
from app.research import routes as research_routes
from app.resolution import routes as identity_routes
from app.signals import routes as signal_routes
from app.simulations import routes as simulation_routes
from app.whatsapp import admin_routes as whatsapp_admin_routes
from app.whatsapp import routes as whatsapp_routes

DEPENDENCY_TIMEOUT_SECONDS = 2


def postgres_check(database_url: str) -> health.ReadinessCheck:
    def check() -> None:
        with psycopg.connect(
            database_url,
            connect_timeout=DEPENDENCY_TIMEOUT_SECONDS,
            options=f"-c statement_timeout={DEPENDENCY_TIMEOUT_SECONDS * 1000}",
        ) as conn:
            conn.execute("SELECT 1")

    return check


def redis_check(client: Redis) -> health.ReadinessCheck:
    def check() -> None:
        client.ping()

    return check


def close_app(app: FastAPI) -> None:
    """Release pooled connections (database engine and Redis client)."""
    app.state.engine.dispose()
    app.state.redis.close()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close_app(app)


def create_app(
    settings: Settings,
    readiness_checks: Mapping[str, health.ReadinessCheck] | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    # No interactive docs: every non-public /api/v1 route requires a session.
    app = FastAPI(title="Hermecious API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)
    clock = clock or SystemClock()
    redis_client = Redis.from_url(
        str(settings.redis_url),
        socket_connect_timeout=DEPENDENCY_TIMEOUT_SECONDS,
        socket_timeout=DEPENDENCY_TIMEOUT_SECONDS,
    )
    if readiness_checks is None:
        readiness_checks = {
            "postgres": postgres_check(str(settings.database_url)),
            "redis": redis_check(redis_client),
        }
    engine = make_engine(str(settings.database_url))
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = engine
    app.state.redis = redis_client
    app.state.session_factory = make_session_factory(engine)
    app.state.login_limiter = LoginRateLimiter(redis_client, clock)
    app.state.readiness_checks = readiness_checks

    app.include_router(health.router)
    app.include_router(auth_routes.public_router)
    app.include_router(auth_routes.router)
    app.include_router(offer_routes.router)
    app.include_router(account_routes.router)
    app.include_router(job_routes.router)
    app.include_router(discovery_routes.router)
    app.include_router(identity_routes.router)
    app.include_router(research_routes.router)
    app.include_router(signal_routes.router)
    app.include_router(qualification_routes.router)
    app.include_router(evaluation_routes.router)
    app.include_router(campaign_routes.router)
    app.include_router(draft_routes.router)
    app.include_router(contact_routes.router)
    app.include_router(approval_routes.router)
    app.include_router(simulation_routes.router)
    app.include_router(whatsapp_routes.router)  # public: HMAC-authenticated Meta webhook
    app.include_router(whatsapp_admin_routes.router)
    assert_api_routes_protected(app)
    install_error_handling(app)
    return app
