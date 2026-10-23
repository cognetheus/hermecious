"""Authentication, CSRF/origin checks and role policy for every protected route (ADR-010 §3, §5).

`authorize_request` is attached to every non-public `/api/v1` router. For
unsafe methods it verifies origin and CSRF *before* any database write.
Role policy: a route may widen access with `allow_roles(...)`; otherwise safe
methods are open to every role and unsafe methods are owner-only.
"""

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, TypeVar
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts

from app.auth import service, tokens
from app.auth.models import Role
from app.core.clock import Clock
from app.core.errors import Forbidden, Unauthenticated
from app.core.settings import Settings
from app.persistence.db import DbSession

logger = logging.getLogger("app.auth")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
ALL_ROLES = frozenset(Role)
PUBLIC_API_PATHS = frozenset({"/api/v1/auth/login"})
_ROLES_ATTR = "_hermecious_allowed_roles"

Endpoint = TypeVar("Endpoint", bound=Callable[..., Any])


class Capability(StrEnum):
    READ = "read"
    MUTATE = "mutate"
    PUBLISH = "publish"
    ADMINISTER = "administer"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.OWNER: frozenset(Capability),
    Role.OPERATOR: frozenset({Capability.READ, Capability.MUTATE}),
    Role.OBSERVER: frozenset({Capability.READ}),
}


def allow_roles(*roles: Role) -> Callable[[Endpoint], Endpoint]:
    """Explicitly widen which roles may call an endpoint (otherwise unsafe methods are owner-only)."""

    def mark(endpoint: Endpoint) -> Endpoint:
        setattr(endpoint, _ROLES_ATTR, frozenset(roles))
        return endpoint

    return mark


def expired_cookie_header(settings: Settings) -> str:
    secure = "; Secure" if settings.session_cookie_secure else ""
    return f"{settings.session_cookie_name}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax{secure}"


def request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin is not None:
        return None if origin == "null" else origin
    referer = request.headers.get("referer")
    if not referer:
        return None
    parts = urlsplit(referer)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else None


def enforce_origin(request: Request, settings: Settings) -> None:
    if request_origin(request) not in settings.allowed_origins:
        logger.warning("auth.csrf_rejected", extra={"context": {"reason": "origin"}})
        raise Forbidden()


def _allowed_roles(request: Request) -> frozenset[Role]:
    endpoint = request.scope.get("endpoint")
    explicit = getattr(endpoint, _ROLES_ATTR, None)
    if explicit is not None:
        return frozenset(explicit)
    return ALL_ROLES if request.method in SAFE_METHODS else frozenset({Role.OWNER})


def authorize_request(request: Request, db: DbSession) -> service.Actor:
    settings: Settings = request.app.state.settings
    clock: Clock = request.app.state.clock
    raw_cookie = request.cookies.get(settings.session_cookie_name)
    clear = {"Set-Cookie": expired_cookie_header(settings)} if raw_cookie is not None else None

    token = tokens.parse_cookie(raw_cookie)
    if token is None:
        if raw_cookie is not None:
            logger.info("auth.session_rejected", extra={"context": {"reason": "malformed_cookie"}})
        raise Unauthenticated(headers=clear)
    now = clock.now()
    loaded = service.load_valid_session(db, token, now)
    if loaded is None:
        raise Unauthenticated(headers=clear)
    session, user = loaded

    # CSRF and role checks happen before the only write below (touch).
    if request.method not in SAFE_METHODS:
        enforce_origin(request, settings)
        if not tokens.csrf_matches(token.verifier, request.headers.get(CSRF_HEADER)):
            logger.warning("auth.csrf_rejected", extra={"context": {"reason": "token"}})
            raise Forbidden()
    role = Role(user.role)
    if role not in _allowed_roles(request):
        logger.warning("auth.forbidden", extra={"context": {"reason": "role"}})
        raise Forbidden()

    service.touch(db, session, now, settings)
    return service.Actor(
        user_id=user.id,
        organization_id=user.organization_id,
        role=role,
        session_id=session.id,
        verifier=token.verifier,
    )


CurrentActor = Annotated[service.Actor, Depends(authorize_request)]


def require_capability(capability: Capability) -> Callable[..., service.Actor]:
    def check(actor: CurrentActor) -> service.Actor:
        if capability not in ROLE_CAPABILITIES[actor.role]:
            logger.warning("auth.forbidden", extra={"context": {"reason": "capability"}})
            raise Forbidden()
        return actor

    return check


def _depends_on(dependant: Dependant | None, dependency: Callable[..., Any]) -> bool:
    if dependant is None:  # cannot inspect: treat as unprotected
        return False
    pending = list(dependant.dependencies)
    while pending:
        current = pending.pop()
        if current.call is dependency:
            return True
        pending.extend(current.dependencies)
    return False


def assert_api_routes_protected(app: FastAPI) -> None:
    """Fail startup if any non-public /api/v1 route can be reached without authorization.

    Uses FastAPI's route-context iteration (the same one its OpenAPI generator uses),
    because included routers are not flattened into `app.routes` since FastAPI 0.16x.
    """
    unprotected = [
        str(context.path)
        for context in iter_route_contexts(app.routes)
        if (context.path or "").startswith("/api/v1")
        and context.path not in PUBLIC_API_PATHS
        and not _depends_on(getattr(context, "dependant", None), authorize_request)
    ]
    if unprotected:
        raise RuntimeError(f"unprotected API routes: {sorted(unprotected)}")
