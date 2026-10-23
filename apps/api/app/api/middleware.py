"""HTTP correlation, request logging and the error envelope.

`RequestContextMiddleware` is the outermost application middleware: it binds a
request ID for the whole request, echoes it as `X-Request-ID`, logs one
`http.request` event, and turns any unhandled exception into the safe
envelope (503 for dependency outages, 500 otherwise), so no traceback or
framework error page reaches the client.
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import (
    DEPENDENCY_EXCEPTIONS,
    AppError,
    ErrorCode,
    code_for_status,
    error_response,
)
from app.core.request_context import (
    REQUEST_ID_HEADER,
    accept_request_id,
    bound_request_id,
    current_request_id,
    new_request_id,
)

logger = logging.getLogger("app.http")


def _record_error(scope: Scope, code: ErrorCode) -> None:
    scope.setdefault("state", {})["error_code"] = code.value


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = accept_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with bound_request_id(request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                if response_started:  # too late for an envelope; let the server close the connection
                    logger.error("http.unhandled_exception", exc_info=exc)
                    raise
                if isinstance(exc, DEPENDENCY_EXCEPTIONS):
                    code, status = ErrorCode.DEPENDENCY_UNAVAILABLE, 503
                    logger.warning(
                        "http.dependency_unavailable", extra={"context": {"error_class": type(exc).__name__}}
                    )
                else:
                    code, status = ErrorCode.INTERNAL_ERROR, 500
                    logger.error("http.unhandled_exception", exc_info=exc)
                _record_error(scope, code)
                await error_response(code, status, request_id)(scope, receive, send_with_request_id)
            finally:
                context: dict[str, Any] = {
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
                error_code = scope.get("state", {}).get("error_code")
                if error_code:
                    context["error_code"] = error_code
                logger.info("http.request", extra={"context": context})


def _request_id() -> str:
    return current_request_id() or new_request_id()


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered for AppError only
        raise exc
    _record_error(request.scope, exc.code)
    return error_response(exc.code, exc.status_code, _request_id(), exc.message, exc.headers)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered for HTTPException only
        raise exc
    code = code_for_status(exc.status_code)
    _record_error(request.scope, code)
    # `exc.detail` is ignored: it may echo request data.
    return error_response(code, exc.status_code, _request_id(), headers=getattr(exc, "headers", None))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    _record_error(request.scope, ErrorCode.VALIDATION_ERROR)
    # Pydantic error details include submitted values, so none are returned.
    return error_response(ErrorCode.VALIDATION_ERROR, 422, _request_id())


def install_error_handling(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(RequestContextMiddleware)
