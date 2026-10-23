"""`/api/v1/auth/*`: login (public), me, csrf, logout (authenticated)."""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.auth import service, tokens
from app.auth.dependencies import CurrentActor, allow_roles, authorize_request, enforce_origin, expired_cookie_header
from app.auth.models import Role, User
from app.core.errors import InvalidRequest, Unauthenticated
from app.core.request_context import current_request_id
from app.core.settings import Settings
from app.persistence.db import DbSession

NO_STORE = {"Cache-Control": "no-store"}

public_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
router = APIRouter(prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(authorize_request)])


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class UserSummary(BaseModel):
    id: uuid.UUID
    display_name: str | None
    email: str
    role: Role
    organization_id: uuid.UUID


def summary(user: User) -> dict[str, object]:
    return UserSummary(
        id=user.id,
        display_name=user.display_name,
        email=user.email_canonical,
        role=Role(user.role),
        organization_id=user.organization_id,
    ).model_dump(mode="json")


def login_preconditions(request: Request) -> None:
    """Login CSRF defence: allowed Origin/Referer and a JSON body (no simple cross-site form posts)."""
    enforce_origin(request, request.app.state.settings)
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json":
        raise InvalidRequest()


@public_router.post("/login", dependencies=[Depends(login_preconditions)])
def login(body: LoginRequest, request: Request, db: DbSession) -> JSONResponse:
    settings: Settings = request.app.state.settings
    user, token = service.login(
        db,
        limiter=request.app.state.login_limiter,
        clock=request.app.state.clock,
        settings=settings,
        email=body.email,
        password=body.password,
        client_ip=request.client.host if request.client else "unknown",
        presented=tokens.parse_cookie(request.cookies.get(settings.session_cookie_name)),
        request_id=current_request_id(),
    )
    response = JSONResponse({"user": summary(user), "csrf_token": tokens.csrf_token(token.verifier)}, headers=NO_STORE)
    response.set_cookie(
        settings.session_cookie_name,
        token.cookie_value,
        max_age=settings.session_absolute_minutes * 60,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me")
def me(actor: CurrentActor, db: DbSession) -> JSONResponse:
    user = db.get(User, actor.user_id)
    if user is None:  # deleted between authorization and read
        raise Unauthenticated()
    return JSONResponse(summary(user), headers=NO_STORE)


@router.get("/csrf")
def csrf(actor: CurrentActor) -> JSONResponse:
    return JSONResponse({"csrf_token": tokens.csrf_token(actor.verifier)}, headers=NO_STORE)


@router.post("/logout", status_code=204)
@allow_roles(Role.OWNER, Role.OPERATOR, Role.OBSERVER)
def logout(request: Request, actor: CurrentActor, db: DbSession) -> Response:
    service.logout(db, actor, request.app.state.clock.now())
    settings: Settings = request.app.state.settings
    return Response(status_code=204, headers={**NO_STORE, "Set-Cookie": expired_cookie_header(settings)})
