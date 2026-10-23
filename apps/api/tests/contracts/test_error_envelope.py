"""A2-A4: one error envelope for every failure, with no tracebacks or submitted data."""

import json
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
import redis.exceptions
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core import errors
from app.main import create_app
from tests.factories import make_settings

Logs = Callable[[], list[dict[str, Any]]]

SETTINGS = make_settings()


class Payload(BaseModel):
    count: int


def app_with_probe_routes() -> FastAPI:
    app = create_app(SETTINGS, readiness_checks={})

    @app.post("/probe/validate")
    def validate(payload: Payload) -> dict[str, int]:
        return {"count": payload.count}

    @app.get("/probe/boom")
    def boom() -> None:
        raise RuntimeError("internal detail: postgresql://u:db-secret-value@h/db at /srv/api/app/x.py")

    @app.get("/probe/postgres-down")
    def postgres_down() -> None:
        raise psycopg.OperationalError("connection to server at db.invalid failed: password=db-secret-value")

    @app.get("/probe/redis-down")
    def redis_down() -> None:
        raise redis.exceptions.ConnectionError("Error 111 connecting to cache.invalid:6379")

    @app.get("/probe/app-error/{kind}")
    def app_error(kind: str) -> None:
        raise {
            "invalid": errors.InvalidRequest,
            "unauthenticated": errors.Unauthenticated,
            "forbidden": errors.Forbidden,
            "not_found": errors.NotFound,
            "conflict": errors.Conflict,
            "rate_limited": errors.RateLimited,
            "dependency": errors.DependencyUnavailable,
        }[kind]()

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app_with_probe_routes(), raise_server_exceptions=False)


def envelope(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id", "retryable"}
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    return dict(body["error"])


def test_validation_error_is_422_without_submitted_data(client: TestClient) -> None:
    response = client.post("/probe/validate", json={"count": "not-a-number-SUBMITTED-VALUE"})
    assert response.status_code == 422
    error = envelope(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["retryable"] is False
    assert "SUBMITTED-VALUE" not in response.text


def test_malformed_json_is_a_safe_validation_error(client: TestClient) -> None:
    response = client.post(
        "/probe/validate", content=b'{"count": 1,,, SECRET-BODY', headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert envelope(response)["code"] == "VALIDATION_ERROR"
    assert "SECRET-BODY" not in response.text


def test_unhandled_error_is_500_without_traceback(client: TestClient, json_logs: Logs) -> None:
    response = client.get("/probe/boom")
    assert response.status_code == 500
    error = envelope(response)
    assert error == {
        "code": "INTERNAL_ERROR",
        "message": "Internal error",
        "request_id": response.headers["x-request-id"],
        "retryable": False,
    }
    for leak in ("Traceback", "RuntimeError", "db-secret-value", "/srv/api", "internal detail"):
        assert leak not in response.text
    logs = json_logs()
    [failure] = [entry for entry in logs if entry["event"] == "http.unhandled_exception"]
    assert failure["request_id"] == error["request_id"]
    assert failure["error"]["class"] == "RuntimeError"
    assert "db-secret-value" not in json.dumps(logs)


@pytest.mark.parametrize("path", ["/probe/postgres-down", "/probe/redis-down"])
def test_dependency_failure_is_retryable_503(client: TestClient, path: str, json_logs: Logs) -> None:
    response = client.get(path)
    assert response.status_code == 503
    error = envelope(response)
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert error["retryable"] is True
    assert "db.invalid" not in response.text and "cache.invalid" not in response.text
    assert "db-secret-value" not in json.dumps(json_logs())


@pytest.mark.parametrize(
    ("kind", "status", "code", "retryable"),
    [
        ("invalid", 400, "VALIDATION_ERROR", False),
        ("unauthenticated", 401, "UNAUTHENTICATED", False),
        ("forbidden", 403, "FORBIDDEN", False),
        ("not_found", 404, "NOT_FOUND", False),
        ("conflict", 409, "CONFLICT", False),
        ("rate_limited", 429, "RATE_LIMITED", True),
        ("dependency", 503, "DEPENDENCY_UNAVAILABLE", True),
    ],
)
def test_typed_app_errors_map_to_stable_codes(
    client: TestClient, kind: str, status: int, code: str, retryable: bool
) -> None:
    response = client.get(f"/probe/app-error/{kind}")
    assert response.status_code == status
    error = envelope(response)
    assert (error["code"], error["retryable"]) == (code, retryable)
    assert error["message"] == errors.DEFAULT_MESSAGES[errors.ErrorCode(code)]


def test_unknown_route_is_not_found_envelope(client: TestClient) -> None:
    response = client.get("/no/such/route?email=someone@example.com")
    assert response.status_code == 404
    assert envelope(response)["code"] == "NOT_FOUND"
    assert "someone@example.com" not in response.text


def test_wrong_method_keeps_405_status_with_envelope(client: TestClient) -> None:
    response = client.delete("/health/live")
    assert response.status_code == 405
    assert envelope(response)["code"] == "VALIDATION_ERROR"


def test_request_log_omits_query_string(client: TestClient, json_logs: Logs) -> None:
    client.get("/health/live?token=query-secret-value&phone=03001234567")
    [request_log] = [entry for entry in json_logs() if entry["event"] == "http.request"]
    assert request_log["context"]["path"] == "/health/live"
    assert "query-secret-value" not in json.dumps(request_log)
    assert "03001234567" not in json.dumps(request_log)


def test_error_code_is_recorded_on_the_request_log(client: TestClient, json_logs: Logs) -> None:
    client.get("/probe/app-error/conflict")
    [request_log] = [entry for entry in json_logs() if entry["event"] == "http.request"]
    assert request_log["context"]["status"] == 409
    assert request_log["context"]["error_code"] == "CONFLICT"
