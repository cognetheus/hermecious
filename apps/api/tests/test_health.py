from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(
    database_url="postgresql://user:db-secret-value@db.invalid:5432/app",
    redis_url="redis://cache.invalid:6379/0",
)


def ok() -> None:
    pass


def failing() -> None:
    raise ConnectionError("could not connect to postgresql://user:db-secret-value@db.invalid")


def client(**checks) -> TestClient:
    return TestClient(create_app(SETTINGS, readiness_checks=checks))


def test_live_is_independent_of_dependencies() -> None:
    response = client(postgres=failing, redis=failing).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_ready_when_all_dependencies_ok() -> None:
    response = client(postgres=ok, redis=ok).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}
    assert response.headers["cache-control"] == "no-store"


def test_not_ready_when_postgres_fails_and_body_is_sanitized() -> None:
    response = client(postgres=failing, redis=ok).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"postgres": "unavailable", "redis": "ok"}}
    assert "db-secret-value" not in response.text
    assert "postgresql://" not in response.text


def test_not_ready_when_redis_fails() -> None:
    response = client(postgres=ok, redis=failing).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "ok", "redis": "unavailable"}


def test_failed_check_is_logged_without_details(caplog) -> None:
    client(postgres=failing, redis=ok).get("/health/ready")
    assert "dependency=postgres error_class=ConnectionError" in caplog.text
    assert "db-secret-value" not in caplog.text
