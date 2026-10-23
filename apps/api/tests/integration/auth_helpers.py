"""Seeding and request helpers for auth integration tests."""

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from app.auth import passwords
from app.auth.models import Organization, OrganizationStatus, Role, User
from tests.factories import TEST_ORIGIN

PASSWORD = "correct-horse-battery-staple"
ORIGIN = {"Origin": TEST_ORIGIN}


def db(app: FastAPI) -> Session:
    session: Session = app.state.session_factory()
    return session


def add_organization(app: FastAPI, name: str = "Test School Ops", status: str = OrganizationStatus.ACTIVE) -> uuid.UUID:
    with db(app) as session:
        org = Organization(name=name, status=status, created_at=app.state.clock.now())
        session.add(org)
        session.commit()
        return org.id


def add_user(
    app: FastAPI,
    organization_id: uuid.UUID,
    email: str,
    role: Role = Role.OWNER,
    password: str = PASSWORD,
    active: bool = True,
) -> uuid.UUID:
    now = app.state.clock.now()
    with db(app) as session:
        user = User(
            organization_id=organization_id,
            email_canonical=passwords.canonical_email(email),
            display_name=f"{role.value} user",
            password_hash=passwords.hash_password(password),
            role=role,
            active=active,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.commit()
        return user.id


def login(client: TestClient, email: str, password: str = PASSWORD, **headers: str) -> Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers={**ORIGIN, **headers})


def logged_in(client: TestClient, email: str, password: str = PASSWORD) -> str:
    """Log in and return the CSRF token; the session cookie stays in the client's jar."""
    response = login(client, email, password)
    assert response.status_code == 200, response.text
    token: str = response.json()["csrf_token"]
    return token


def mutation_headers(csrf: str, **extra: Any) -> dict[str, str]:
    return {**ORIGIN, "X-CSRF-Token": csrf, **extra}
