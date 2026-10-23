"""Login, session validation, rotation and revocation (ADR-010).

Every decision reads Postgres; nothing about identity or role is taken from the client.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import passwords, tokens
from app.auth.models import AuthSession, Organization, OrganizationStatus, Role, User
from app.auth.rate_limit import LoginRateLimiter
from app.core.clock import Clock
from app.core.errors import Unauthenticated
from app.core.settings import Settings

logger = logging.getLogger("app.auth")

TOUCH_INTERVAL = timedelta(minutes=5)
INVALID_CREDENTIALS = "Invalid email or password"


@dataclass(frozen=True)
class Actor:
    """The authenticated principal for one request. Organization scope comes from here only."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: Role
    session_id: uuid.UUID
    verifier: str = field(repr=False)


def _reject(reason: str) -> None:
    logger.info("auth.session_rejected", extra={"context": {"reason": reason}})


def _revoke(db: Session, session_id: uuid.UUID, now: datetime, reason: str) -> None:
    result = db.execute(
        update(AuthSession).where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None)).values(revoked_at=now)
    )
    db.commit()
    if getattr(result, "rowcount", 0):
        logger.info("auth.session_revoked", extra={"context": {"reason": reason}})


def load_valid_session(db: Session, token: tokens.SessionToken, now: datetime) -> tuple[AuthSession, User] | None:
    row = db.execute(
        select(AuthSession, User, Organization)
        .join(User, AuthSession.user_id == User.id)
        .join(Organization, User.organization_id == Organization.id)
        .where(AuthSession.id == token.session_id)
    ).one_or_none()
    if row is None:
        _reject("unknown_session")
        return None
    session, user, organization = row
    if not tokens.verifier_matches(token.verifier, session.verifier_hash):
        _reject("verifier_mismatch")  # do not revoke: the caller may not own this session
        return None
    if session.revoked_at is not None:
        _reject("revoked")
        return None
    if now >= session.idle_expires_at or now >= session.absolute_expires_at:
        _reject("expired")
        return None
    if user.credentials_changed_at is not None and user.credentials_changed_at > session.issued_at:
        _revoke(db, session.id, now, "credentials_changed")
        return None
    if not user.active or organization.status != OrganizationStatus.ACTIVE:
        _revoke(db, session.id, now, "principal_inactive")
        return None
    return session, user


def touch(db: Session, session: AuthSession, now: datetime, settings: Settings) -> None:
    """Slide the idle window, writing at most once per TOUCH_INTERVAL and never past absolute expiry."""
    if session.last_seen_at is not None and now - session.last_seen_at < TOUCH_INTERVAL:
        return
    session.last_seen_at = now
    session.idle_expires_at = min(now + timedelta(minutes=settings.session_idle_minutes), session.absolute_expires_at)
    db.commit()


def issue_session(
    db: Session, user: User, now: datetime, settings: Settings, request_id: str | None
) -> tokens.SessionToken:
    token = tokens.new_token()
    absolute = now + timedelta(minutes=settings.session_absolute_minutes)
    db.add(
        AuthSession(
            id=token.session_id,
            user_id=user.id,
            verifier_hash=tokens.verifier_hash(token.verifier),
            issued_at=now,
            last_seen_at=now,
            idle_expires_at=min(now + timedelta(minutes=settings.session_idle_minutes), absolute),
            absolute_expires_at=absolute,
            created_request_id=request_id,
        )
    )
    return token


def login(
    db: Session,
    *,
    limiter: LoginRateLimiter,
    clock: Clock,
    settings: Settings,
    email: str,
    password: str,
    client_ip: str,
    presented: tokens.SessionToken | None,
    request_id: str | None,
) -> tuple[User, tokens.SessionToken]:
    email = passwords.canonical_email(email)
    limiter.check_and_count(email, client_ip)

    rows = db.execute(
        select(User, Organization)
        .join(Organization, User.organization_id == Organization.id)
        .where(User.email_canonical == email)
    ).all()
    user, organization = rows[0] if len(rows) == 1 else (None, None)
    # Always verify (against a dummy hash for unknown users) so failures cost the same.
    password_ok = passwords.verify_password(user.password_hash if user else None, password)
    if (
        user is None
        or organization is None
        or not password_ok
        or not user.active
        or organization.status != OrganizationStatus.ACTIVE
    ):
        limiter.record_failure(email)
        logger.info("auth.login_denied", extra={"context": {"reason": "invalid_credentials"}})
        raise Unauthenticated(INVALID_CREDENTIALS)

    limiter.reset(email)
    now = clock.now()
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        user.updated_at = now
    # Fixation defence: a session presented with the login is revoked, never reused.
    if presented is not None:
        existing = db.get(AuthSession, presented.session_id)
        if existing is not None and tokens.verifier_matches(presented.verifier, existing.verifier_hash):
            existing.revoked_at = existing.revoked_at or now
    token = issue_session(db, user, now, settings, request_id)
    db.commit()
    logger.info("auth.login_succeeded")
    return user, token


def logout(db: Session, actor: Actor, now: datetime) -> None:
    _revoke(db, actor.session_id, now, "logout")
    logger.info("auth.logout")
