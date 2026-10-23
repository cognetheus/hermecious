"""Typed application errors and the single HTTP error envelope:

    {"error": {"code": "...", "message": "...", "request_id": "...", "retryable": false}}

Messages are fixed, safe strings. Submitted data, exception text and
tracebacks never reach the client.
"""

from enum import StrEnum

import psycopg
import redis.exceptions
import sqlalchemy.exc
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


DEFAULT_MESSAGES = {
    ErrorCode.VALIDATION_ERROR: "Request could not be processed",
    ErrorCode.UNAUTHENTICATED: "Authentication required",
    ErrorCode.FORBIDDEN: "Not permitted",
    ErrorCode.NOT_FOUND: "Resource not found",
    ErrorCode.CONFLICT: "Request conflicts with current state",
    ErrorCode.RATE_LIMITED: "Too many requests",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "A required service is temporarily unavailable",
    ErrorCode.INTERNAL_ERROR: "Internal error",
}

RETRYABLE = frozenset({ErrorCode.RATE_LIMITED, ErrorCode.DEPENDENCY_UNAVAILABLE})

# Framework/HTTP statuses that keep their status but need a stable code.
STATUS_CODES = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.DEPENDENCY_UNAVAILABLE,
}

# Driver errors that mean "a dependency is down", mapped to 503 instead of 500.
DEPENDENCY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    psycopg.OperationalError,
    sqlalchemy.exc.OperationalError,
    sqlalchemy.exc.DisconnectionError,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
)


def code_for_status(status_code: int) -> ErrorCode:
    if status_code in STATUS_CODES:
        return STATUS_CODES[status_code]
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.VALIDATION_ERROR


class AppError(Exception):
    """Base for errors that application code raises deliberately."""

    code = ErrorCode.INTERNAL_ERROR
    status_code = 500

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        # `message` must be a fixed, developer-written string: it is sent to the client.
        self.message = message or DEFAULT_MESSAGES[self.code]
        self.headers = headers
        super().__init__(self.message)


class InvalidRequest(AppError):
    code, status_code = ErrorCode.VALIDATION_ERROR, 400


class Unauthenticated(AppError):
    code, status_code = ErrorCode.UNAUTHENTICATED, 401


class Forbidden(AppError):
    code, status_code = ErrorCode.FORBIDDEN, 403


class NotFound(AppError):
    code, status_code = ErrorCode.NOT_FOUND, 404


class Conflict(AppError):
    code, status_code = ErrorCode.CONFLICT, 409


class RateLimited(AppError):
    code, status_code = ErrorCode.RATE_LIMITED, 429


class DependencyUnavailable(AppError):
    code, status_code = ErrorCode.DEPENDENCY_UNAVAILABLE, 503


def error_response(
    code: ErrorCode,
    status_code: int,
    request_id: str,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code.value,
            "message": message or DEFAULT_MESSAGES[code],
            "request_id": request_id,
            "retryable": code in RETRYABLE,
        }
    }
    return JSONResponse(body, status_code=status_code, headers={**(headers or {}), "Cache-Control": "no-store"})
