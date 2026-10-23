from collections.abc import Mapping

import psycopg
from fastapi import FastAPI
from redis import Redis

from app.api import health
from app.api.middleware import install_error_handling
from app.core.settings import Settings

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


def create_app(settings: Settings, readiness_checks: Mapping[str, health.ReadinessCheck] | None = None) -> FastAPI:
    app = FastAPI(title="Hermecious API")
    if readiness_checks is None:
        redis_client = Redis.from_url(
            str(settings.redis_url),
            socket_connect_timeout=DEPENDENCY_TIMEOUT_SECONDS,
            socket_timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
        readiness_checks = {
            "postgres": postgres_check(str(settings.database_url)),
            "redis": redis_check(redis_client),
        }
    app.state.readiness_checks = readiness_checks
    app.include_router(health.router)
    install_error_handling(app)
    return app
