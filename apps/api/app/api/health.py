"""Liveness and readiness probes.

`/health/live` answers whenever the process can serve HTTP and never touches
dependencies. `/health/ready` probes every registered dependency with a
bounded timeout and reports only `ok` or `unavailable` per dependency, never
connection details or exception text.
"""

import logging
from collections.abc import Callable, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

# A readiness check returns normally when the dependency is usable and raises otherwise.
ReadinessCheck = Callable[[], None]

NO_STORE = {"Cache-Control": "no-store"}


@router.get("/live")
def live() -> JSONResponse:
    return JSONResponse({"status": "alive"}, headers=NO_STORE)


@router.get("/ready")
def ready(request: Request) -> JSONResponse:
    checks: Mapping[str, ReadinessCheck] = request.app.state.readiness_checks
    statuses: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            statuses[name] = "ok"
        except Exception as exc:  # any failure means "not ready"; details stay server-side
            logger.warning("readiness check failed: dependency=%s error_class=%s", name, type(exc).__name__)
            statuses[name] = "unavailable"
    is_ready = all(status == "ok" for status in statuses.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": statuses},
        status_code=200 if is_ready else 503,
        headers=NO_STORE,
    )
