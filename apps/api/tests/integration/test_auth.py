"""P1.1 acceptance: AUTH-01..AUTH-08 against real Postgres and Redis."""

import json
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import tokens
from app.auth.bootstrap import BootstrapRefused, bootstrap_owner
from app.auth.dependencies import Capability, CurrentActor, allow_roles, authorize_request, require_capability
from app.auth.models import AuthSession, Organization, OrganizationStatus, Role, User
from app.auth.service import Actor
from app.core.clock import FixedClock
from app.core.settings import Settings
from app.main import create_app
from tests.integration.auth_helpers import (
    ORIGIN,
    PASSWORD,
    add_organization,
    add_user,
    db,
    logged_in,
    login,
    mutation_headers,
)
from tests.integration.db import API_ROOT

Logs = Callable[[], list[dict[str, Any]]]
OWNER = "owner@school-ops.example"


def session_rows(app: FastAPI) -> list[AuthSession]:
    with db(app) as session:
        return list(session.scalars(select(AuthSession).order_by(AuthSession.issued_at)))


def cookie_name(app: FastAPI) -> str:
    settings: Settings = app.state.settings
    return settings.session_cookie_name


# --- AUTH-01: owner bootstrap ---------------------------------------------------------------


def test_bootstrap_creates_one_org_and_owner_and_refuses_a_second(app: FastAPI, clock: FixedClock) -> None:
    with db(app) as session:
        owner = bootstrap_owner(
            session, organization_name="CoderzHunt", email=OWNER, password=PASSWORD, display_name="Owner", clock=clock
        )
        assert owner.role == Role.OWNER
        assert owner.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=1$")
        assert PASSWORD not in owner.password_hash
    with db(app) as session, pytest.raises(BootstrapRefused, match="already bootstrapped"):
        bootstrap_owner(
            session, organization_name="Other", email="x@y.example", password=PASSWORD, display_name=None, clock=clock
        )
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 1
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_concurrent_bootstraps_create_exactly_one_owner(app: FastAPI, clock: FixedClock) -> None:
    outcomes: list[str] = []
    barrier = threading.Barrier(4)

    def attempt(i: int) -> None:
        barrier.wait()
        with db(app) as session:
            try:
                bootstrap_owner(
                    session,
                    organization_name=f"Org {i}",
                    email=f"owner{i}@example.com",
                    password=PASSWORD,
                    display_name=None,
                    clock=clock,
                )
                outcomes.append("created")
            except BootstrapRefused:
                outcomes.append("refused")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["created", "refused", "refused", "refused"]
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    ("password", "message"),
    [("short", "12-256"), ("x" * 257, "12-256"), (OWNER, "must not equal")],
    ids=["short", "long", "equals-email"],
)
def test_bootstrap_rejects_weak_passwords(app: FastAPI, clock: FixedClock, password: str, message: str) -> None:
    with db(app) as session, pytest.raises(BootstrapRefused, match=message):
        bootstrap_owner(
            session, organization_name="CoderzHunt", email=OWNER, password=password, display_name=None, clock=clock
        )


def test_bootstrap_cli_has_no_password_flag_and_needs_a_tty() -> None:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # fixed argv
            [sys.executable, "-m", "app.auth.bootstrap", *args],
            cwd=API_ROOT,
            input="hunter2hunter2\nhunter2hunter2\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    with_flag = run("--organization", "X", "--email", OWNER, "--password", "hunter2hunter2")
    assert with_flag.returncode == 2 and "unrecognized arguments: --password" in with_flag.stderr
    piped = run("--organization", "X", "--email", OWNER)
    assert piped.returncode == 2 and "interactive terminal" in piped.stderr


# --- AUTH-02: uniform denial and rate limiting --------------------------------------------


def test_bad_password_unknown_email_disabled_user_and_suspended_org_look_identical(
    app: FastAPI, client: TestClient, json_logs: Logs
) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    add_user(app, org, "disabled@school-ops.example", role=Role.OPERATOR, active=False)
    suspended = add_organization(app, "Suspended", status=OrganizationStatus.SUSPENDED)
    add_user(app, suspended, "suspended@school-ops.example")

    attempts = [
        login(client, OWNER, "wrong-password-value"),
        login(client, "nobody@school-ops.example"),
        login(client, "disabled@school-ops.example"),
        login(client, "suspended@school-ops.example"),
    ]
    bodies = []
    for response in attempts:
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
        error = response.json()["error"]
        bodies.append({k: v for k, v in error.items() if k != "request_id"})
    assert bodies == [{"code": "UNAUTHENTICATED", "message": "Invalid email or password", "retryable": False}] * 4
    logs = json.dumps(json_logs())
    for leak in ("wrong-password-value", PASSWORD, "school-ops.example", "nobody@"):
        assert leak not in logs
    assert session_rows(app) == []


def test_email_lockout_after_five_failures_even_with_correct_password(
    app: FastAPI, client: TestClient, clock: FixedClock
) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    add_user(app, org, "other@school-ops.example")
    for _ in range(5):
        assert login(client, OWNER, "wrong-password-value").status_code == 401
    locked = login(client, OWNER)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "RATE_LIMITED" and locked.json()["error"]["retryable"] is True
    assert 0 < int(locked.headers["retry-after"]) <= 900
    assert login(client, "other@school-ops.example").status_code == 200  # other accounts unaffected
    clock.advance(timedelta(minutes=15))
    assert login(client, OWNER).status_code == 200  # window expired


def test_ip_budget_limits_enumeration_across_emails(app: FastAPI, client: TestClient) -> None:
    statuses = [login(client, f"probe{i}@school-ops.example").status_code for i in range(31)]
    assert statuses[:30] == [401] * 30
    assert statuses[30] == 429


def test_redis_outage_fails_login_closed_but_keeps_sessions(
    app: FastAPI, client: TestClient, app_settings: Settings, clock: FixedClock
) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    broken = create_app(app_settings.model_copy(update={"redis_url": "redis://127.0.0.1:1/0"}), clock=clock)
    broken_client = TestClient(broken, raise_server_exceptions=False)
    broken_client.cookies = client.cookies
    denied = login(broken_client, OWNER)
    assert denied.status_code == 503
    assert denied.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert broken_client.get("/api/v1/auth/me").status_code == 200  # Postgres-backed session still valid
    broken.state.engine.dispose()


# --- AUTH-03: successful login --------------------------------------------------------------


def test_login_sets_hardened_opaque_cookie_and_me_is_safe(app: FastAPI, client: TestClient, json_logs: Logs) -> None:
    org = add_organization(app)
    user_id = add_user(app, org, OWNER)
    response = login(client, "  Owner@School-Ops.example ")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    name = cookie_name(app)
    assert cookie.startswith(f"{name}=")
    for attribute in ("HttpOnly", "Path=/", "SameSite=lax", "Max-Age=86400"):
        assert attribute.lower() in cookie.lower()
    assert "domain" not in cookie.lower()
    value = client.cookies[name]
    token = tokens.parse_cookie(value)
    assert token is not None

    body = response.json()
    assert body["user"] == {
        "id": str(user_id),
        "display_name": "owner user",
        "email": OWNER,
        "role": "owner",
        "organization_id": str(org),
    }
    assert body["csrf_token"] == tokens.csrf_token(token.verifier)

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json() == body["user"]
    assert "password" not in me.text and "hash" not in me.text

    [row] = session_rows(app)
    assert row.id == token.session_id
    assert row.verifier_hash == tokens.verifier_hash(token.verifier) != token.verifier
    logs = json.dumps(json_logs())
    assert token.verifier not in logs and value not in logs and PASSWORD not in logs


def test_csrf_endpoint_requires_session_and_returns_bound_token(app: FastAPI, client: TestClient) -> None:
    assert client.get("/api/v1/auth/csrf").status_code == 401
    org = add_organization(app)
    add_user(app, org, OWNER)
    csrf = logged_in(client, OWNER)
    assert client.get("/api/v1/auth/csrf").json() == {"csrf_token": csrf}


# --- AUTH-04: tampering and expiry ----------------------------------------------------------


@pytest.mark.parametrize("tamper", ["verifier", "unknown_id", "malformed", "empty"])
def test_tampered_cookies_are_rejected_and_cleared(app: FastAPI, client: TestClient, tamper: str) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    name = cookie_name(app)
    token = tokens.parse_cookie(client.cookies[name])
    assert token is not None
    forged = {
        "verifier": f"{token.session_id.hex}.{tokens.new_token().verifier}",
        "unknown_id": tokens.new_token().cookie_value,
        "malformed": "not-a-session' OR 1=1 --",
        "empty": "",
    }[tamper]
    before = session_rows(app)
    response = TestClient(app, raise_server_exceptions=False, cookies={name: forged}).get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert "Max-Age=0" in response.headers.get("set-cookie", "")
    after = session_rows(app)
    assert [(s.id, s.revoked_at, s.idle_expires_at) for s in after] == [
        (s.id, s.revoked_at, s.idle_expires_at) for s in before
    ]
    assert client.get("/api/v1/auth/me").status_code == 200  # the real session was not revoked


def test_idle_expiry_and_exact_edge(app: FastAPI, client: TestClient, clock: FixedClock) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    clock.advance(timedelta(hours=8) - timedelta(seconds=1))
    assert client.get("/api/v1/auth/me").status_code == 200  # slides idle window (touch)
    clock.advance(timedelta(hours=8))  # exactly at the new idle expiry
    assert client.get("/api/v1/auth/me").status_code == 401
    [row] = session_rows(app)
    assert row.revoked_at is None and row.idle_expires_at == clock.now()  # not prolonged by the failed request


def test_absolute_expiry_cannot_be_extended_by_activity(app: FastAPI, client: TestClient, clock: FixedClock) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    for _ in range(5):  # activity every 4h keeps the idle window alive...
        clock.advance(timedelta(hours=4))
        assert client.get("/api/v1/auth/me").status_code == 200
    clock.advance(timedelta(hours=4))  # ...but not past 24h absolute
    assert client.get("/api/v1/auth/me").status_code == 401
    [row] = session_rows(app)
    assert row.idle_expires_at <= row.absolute_expires_at


def test_last_seen_is_written_at_most_every_five_minutes(app: FastAPI, client: TestClient, clock: FixedClock) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    issued = session_rows(app)[0].last_seen_at
    clock.advance(timedelta(minutes=4))
    client.get("/api/v1/auth/me")
    assert session_rows(app)[0].last_seen_at == issued
    clock.advance(timedelta(minutes=1))
    client.get("/api/v1/auth/me")
    assert session_rows(app)[0].last_seen_at == clock.now()


# --- AUTH-05: revocation ----------------------------------------------------------------------


def test_logout_revokes_immediately_and_replay_fails(app: FastAPI, client: TestClient, json_logs: Logs) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    csrf = logged_in(client, OWNER)
    stolen = dict(client.cookies)
    response = client.post("/api/v1/auth/logout", headers=mutation_headers(csrf))
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    replay = TestClient(app, raise_server_exceptions=False, cookies=stolen)
    assert replay.get("/api/v1/auth/me").status_code == 401
    assert replay.post("/api/v1/auth/logout", headers=mutation_headers(csrf)).status_code == 401
    [row] = session_rows(app)
    assert row.revoked_at is not None
    assert [e["event"] for e in json_logs() if e["event"].startswith("auth.")].count("auth.logout") == 1


def test_disabling_the_user_revokes_live_sessions(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    user_id = add_user(app, org, OWNER)
    logged_in(client, OWNER)
    with db(app) as session:
        user = session.get(User, user_id)
        assert user is not None
        user.active = False
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert session_rows(app)[0].revoked_at is not None


def test_suspending_the_organization_blocks_sessions(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    with db(app) as session:
        organization = session.get(Organization, org)
        assert organization is not None
        organization.status = OrganizationStatus.SUSPENDED
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_credential_change_invalidates_older_sessions(app: FastAPI, client: TestClient, clock: FixedClock) -> None:
    org = add_organization(app)
    user_id = add_user(app, org, OWNER)
    logged_in(client, OWNER)
    clock.advance(timedelta(minutes=1))
    with db(app) as session:
        user = session.get(User, user_id)
        assert user is not None
        user.credentials_changed_at = clock.now()
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    clock.advance(timedelta(seconds=1))
    logged_in(client, OWNER)  # a fresh login after the change works
    assert client.get("/api/v1/auth/me").status_code == 200


# --- AUTH-06: CSRF and origin ----------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://localhost:3000"},  # no token
        {"Origin": "http://localhost:3000", "X-CSRF-Token": "forged-token"},
        {"Origin": "https://evil.example", "X-CSRF-Token": "<valid>"},
        {"Origin": "null", "X-CSRF-Token": "<valid>"},
        {"X-CSRF-Token": "<valid>"},  # neither Origin nor Referer
        {"Referer": "https://evil.example/page", "X-CSRF-Token": "<valid>"},
        {"Origin": "http://localhost:3000.evil.example", "X-CSRF-Token": "<valid>"},
    ],
    ids=["missing-token", "wrong-token", "cross-origin", "null-origin", "no-origin", "cross-referer", "lookalike"],
)
def test_logout_without_valid_csrf_and_origin_is_403_and_changes_nothing(
    app: FastAPI, client: TestClient, headers: dict[str, str]
) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    csrf = logged_in(client, OWNER)
    before = [(s.revoked_at, s.last_seen_at, s.idle_expires_at) for s in session_rows(app)]
    sent = {k: (csrf if v == "<valid>" else v) for k, v in headers.items()}
    response = client.post("/api/v1/auth/logout", headers=sent)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert [(s.revoked_at, s.last_seen_at, s.idle_expires_at) for s in session_rows(app)] == before
    assert client.get("/api/v1/auth/me").status_code == 200


def test_same_origin_referer_is_accepted_when_origin_is_stripped(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    csrf = logged_in(client, OWNER)
    response = client.post(
        "/api/v1/auth/logout", headers={"Referer": "http://localhost:3000/settings", "X-CSRF-Token": csrf}
    )
    assert response.status_code == 204


def test_csrf_token_from_a_rotated_session_is_rejected(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    old_csrf = logged_in(client, OWNER)
    logged_in(client, OWNER)  # rotation: a new session replaces the old one
    assert client.post("/api/v1/auth/logout", headers=mutation_headers(old_csrf)).status_code == 403


def test_login_csrf_defences(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    body = {"email": OWNER, "password": PASSWORD}
    cross_site = client.post("/api/v1/auth/login", json=body, headers={"Origin": "https://evil.example"})
    assert cross_site.status_code == 403
    no_origin = client.post("/api/v1/auth/login", json=body)
    assert no_origin.status_code == 403
    form_post = client.post(
        "/api/v1/auth/login",
        content=f"email={OWNER}&password={PASSWORD}",
        headers={**ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert form_post.status_code == 400
    text_plain = client.post(
        "/api/v1/auth/login", content=json.dumps(body), headers={**ORIGIN, "Content-Type": "text/plain"}
    )
    assert text_plain.status_code == 400
    assert session_rows(app) == []


# --- AUTH-07: roles and organization scope ----------------------------------------------------

effects: list[str] = []
probe = APIRouter(prefix="/api/v1/probe", dependencies=[Depends(authorize_request)])
Publisher = Annotated[Actor, Depends(require_capability(Capability.PUBLISH))]


@probe.get("/read")
def probe_read(actor: CurrentActor, organization_id: str | None = None) -> dict[str, str]:
    return {"organization_id": str(actor.organization_id)}  # query parameter deliberately ignored


@probe.post("/mutate")
def probe_mutate(actor: CurrentActor) -> dict[str, str]:
    effects.append(f"mutate:{actor.role}")
    return {"ok": "mutate"}


@probe.post("/draft")
@allow_roles(Role.OWNER, Role.OPERATOR)
def probe_draft(actor: CurrentActor) -> dict[str, str]:
    effects.append(f"draft:{actor.role}")
    return {"ok": "draft"}


@probe.post("/publish")
@allow_roles(Role.OWNER, Role.OPERATOR, Role.OBSERVER)  # widened on purpose: capability check must still deny
def probe_publish(actor: Publisher) -> dict[str, str]:
    effects.append(f"publish:{actor.role}")
    return {"ok": "publish"}


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.OWNER, {"read": 200, "mutate": 200, "draft": 200, "publish": 200}),
        (Role.OPERATOR, {"read": 200, "mutate": 403, "draft": 200, "publish": 403}),
        (Role.OBSERVER, {"read": 200, "mutate": 403, "draft": 403, "publish": 403}),
    ],
)
def test_role_matrix_denies_lower_roles_before_any_effect(
    app: FastAPI, client: TestClient, role: Role, expected: dict[str, int]
) -> None:
    app.include_router(probe)
    effects.clear()
    org = add_organization(app)
    add_user(app, org, f"{role.value}@school-ops.example", role=role)
    csrf = logged_in(client, f"{role.value}@school-ops.example")
    got = {"read": client.get("/api/v1/probe/read").status_code}
    for action in ("mutate", "draft", "publish"):
        got[action] = client.post(f"/api/v1/probe/{action}", headers=mutation_headers(csrf)).status_code
    assert got == expected
    allowed = [a for a in ("mutate", "draft", "publish") if expected[a] == 200]
    assert effects == [f"{a}:{role.value}" for a in allowed]


def test_client_supplied_organization_is_ignored(app: FastAPI, client: TestClient) -> None:
    app.include_router(probe)
    org = add_organization(app)
    other = add_organization(app, "Other Org")
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    response = client.get("/api/v1/probe/read", params={"organization_id": str(other)})
    assert response.json() == {"organization_id": str(org)}


def test_anonymous_requests_never_reach_handlers(app: FastAPI, client: TestClient) -> None:
    app.include_router(probe)
    effects.clear()
    for action in ("mutate", "draft", "publish"):
        assert client.post(f"/api/v1/probe/{action}", headers=ORIGIN).status_code == 401
    assert client.get("/api/v1/probe/read").status_code == 401
    assert effects == []


# --- AUTH-08 and failure simulations -----------------------------------------------------------


def test_sessions_survive_an_api_restart(app: FastAPI, client: TestClient, app_settings: Settings) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    restarted = create_app(app_settings, clock=app.state.clock)  # new process state, same database
    again = TestClient(restarted, raise_server_exceptions=False)
    again.cookies = client.cookies
    assert again.get("/api/v1/auth/me").status_code == 200
    restarted.state.engine.dispose()


def test_database_outage_is_a_safe_503(app: FastAPI, client: TestClient, app_settings: Settings) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    down = create_app(
        app_settings.model_copy(update={"database_url": "postgresql://u:db-secret-value@127.0.0.1:1/x_test"}),
        clock=app.state.clock,
    )
    down_client = TestClient(down, raise_server_exceptions=False)
    down_client.cookies = client.cookies
    response = down_client.get("/api/v1/auth/me")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "db-secret-value" not in response.text
    down.state.engine.dispose()


def test_login_rotates_and_revokes_a_presented_session(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    logged_in(client, OWNER)
    first = client.cookies[cookie_name(app)]
    logged_in(client, OWNER)
    second = client.cookies[cookie_name(app)]
    assert first != second
    old, new = session_rows(app)
    assert old.revoked_at is not None and new.revoked_at is None
    fixated = TestClient(app, raise_server_exceptions=False, cookies={cookie_name(app): first})
    assert fixated.get("/api/v1/auth/me").status_code == 401


def test_parallel_logins_create_distinct_sessions(app: FastAPI) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    statuses: list[int] = []

    def attempt() -> None:
        statuses.append(login(TestClient(app, raise_server_exceptions=False), OWNER).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [200] * 5
    rows = session_rows(app)
    assert len(rows) == 5 and len({r.verifier_hash for r in rows}) == 5


def test_logout_racing_a_request_leaves_no_usable_session(app: FastAPI, client: TestClient) -> None:
    org = add_organization(app)
    add_user(app, org, OWNER)
    csrf = logged_in(client, OWNER)
    results: dict[str, int] = {}

    def logout() -> None:
        results["logout"] = client.post("/api/v1/auth/logout", headers=mutation_headers(csrf)).status_code

    def read() -> None:
        results["me"] = client.get("/api/v1/auth/me").status_code

    threads = [threading.Thread(target=logout), threading.Thread(target=read)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["logout"] == 204 and results["me"] in {200, 401}
    assert client.get("/api/v1/auth/me").status_code == 401


def test_log_injection_in_credentials_is_contained(app: FastAPI, client: TestClient, json_logs: Logs) -> None:
    hostile = 'evil\n{"event":"auth.login_succeeded","level":"info"}@x.example'
    assert login(client, hostile).status_code == 401
    events = [e["event"] for e in json_logs() if e["logger"].startswith("app.")]
    assert "auth.login_succeeded" not in events
    assert "auth.login_denied" in events
