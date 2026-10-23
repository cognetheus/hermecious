"""A1/A7/A8: request IDs correlate responses with logs, never leak across requests."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_context import current_request_id
from app.core.settings import Settings
from app.main import create_app

Logs = Callable[[], list[dict[str, Any]]]

SETTINGS = Settings.model_validate(
    {"environment": "test", "database_url": "postgresql://u:p@db.invalid/app", "redis_url": "redis://r.invalid:6379/0"}
)


def app_with_echo() -> FastAPI:
    app = create_app(SETTINGS, readiness_checks={})

    @app.get("/probe/echo")
    async def echo() -> dict[str, str | None]:
        await asyncio.sleep(0)  # yield so concurrent requests interleave
        seen = current_request_id()
        await asyncio.sleep(0.01)
        return {"seen": seen, "still": current_request_id()}

    return app


def test_generated_id_matches_header_and_log(json_logs: Logs) -> None:
    response = TestClient(create_app(SETTINGS, readiness_checks={})).get("/health/live")
    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    [entry] = [e for e in json_logs() if e["event"] == "http.request"]
    assert entry["request_id"] == request_id
    assert entry["context"]["status"] == 200
    assert isinstance(entry["context"]["duration_ms"], float)


def test_safe_client_id_is_propagated(json_logs: Logs) -> None:
    client = TestClient(create_app(SETTINGS, readiness_checks={}))
    response = client.get("/health/live", headers={"X-Request-ID": "proxy-trace-0001"})
    assert response.headers["x-request-id"] == "proxy-trace-0001"
    assert [e["request_id"] for e in json_logs() if e["event"] == "http.request"] == ["proxy-trace-0001"]


@pytest.mark.parametrize(
    "hostile",
    [
        "x" * 100_000,
        'abcdefgh"},"event":"auth.login_succeeded',
        "abcdefgh\\nforged",
        "<script>alert(1)</script>",
    ],
    ids=["oversized", "json-injection", "newline", "markup"],
)
def test_hostile_client_ids_are_replaced(hostile: str, json_logs: Logs) -> None:
    client = TestClient(create_app(SETTINGS, readiness_checks={}))
    response = client.get("/health/live", headers={"X-Request-ID": hostile})
    issued = response.headers["x-request-id"]
    assert issued != hostile and issued.startswith("req_") and len(issued) == 36
    lines = [e for e in json_logs() if e["logger"].startswith("app.")]
    assert [e["event"] for e in lines] == ["http.request"]
    assert lines[0]["request_id"] == issued
    assert hostile not in json.dumps(json_logs())


def test_concurrent_requests_never_share_context() -> None:
    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app_with_echo())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(*(client.get("/probe/echo") for _ in range(100)))

    responses = asyncio.run(run())
    issued = [r.headers["x-request-id"] for r in responses]
    assert len(set(issued)) == 100
    for response in responses:
        body = response.json()
        assert body["seen"] == body["still"] == response.headers["x-request-id"]
    assert current_request_id() is None


def test_context_is_cleared_after_each_request() -> None:
    client = TestClient(app_with_echo())
    first = client.get("/probe/echo").json()["seen"]
    second = client.get("/probe/echo").json()["seen"]
    assert first != second
    assert current_request_id() is None
