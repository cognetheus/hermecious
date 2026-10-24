"""P1.4 acceptance (API): ACCOUNT-01..ACCOUNT-10 over HTTP with real sessions, CSRF and Postgres."""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.accounts.models import Account, AccountFact, ActionAudit, SourceRecord
from app.auth.models import Role
from app.core.clock import FixedClock
from app.core.settings import Settings
from app.main import close_app, create_app
from tests.integration.auth_helpers import ORIGIN, add_organization, add_user, db, logged_in, mutation_headers

BASE = "/api/v1/accounts"


@dataclass
class Team:
    app: FastAPI
    org: uuid.UUID
    clients: dict[Role, TestClient]
    csrf: dict[Role, str]
    user_ids: dict[Role, uuid.UUID]

    def send(self, role: Role, method: str, path: str, body: Any = None, **headers: str) -> Any:
        return self.clients[role].request(
            method, path, json=body, headers={**mutation_headers(self.csrf[role]), **headers}
        )

    def get(self, role: Role, path: str, **params: Any) -> Any:
        return self.clients[role].get(path, params=params)

    def create(
        self, name: str = "Crescent Valley Grammar School (Synthetic)", role: Role = Role.OPERATOR, **extra: Any
    ) -> dict[str, Any]:
        response = self.send(role, "POST", BASE, {"canonical_name": name, "locality": "Johar Town", **extra})
        assert response.status_code == 201, response.text
        return dict(response.json())


@pytest.fixture
def team(app: FastAPI) -> Team:
    org = add_organization(app)
    clients, csrf, ids = {}, {}, {}
    for role in Role:
        email = f"{role.value}@accounts.example"
        ids[role] = add_user(app, org, email, role=role)
        clients[role] = TestClient(app, raise_server_exceptions=False)
        csrf[role] = logged_in(clients[role], email)
    return Team(app, org, clients, csrf, ids)


def now(team: Team) -> str:
    clock: FixedClock = team.app.state.clock
    return clock.now().isoformat()


def supported_fact(team: Team, **overrides: Any) -> dict[str, Any]:
    clock: FixedClock = team.app.state.clock
    observed = (clock.now() - timedelta(hours=2)).isoformat()
    return {
        "claim_type": "campus_count",
        "value": {"count": 2},
        "verification_status": "source_supported",
        "confidence_label": "moderate",
        "observed_at": observed,
        "evidence_excerpt": "Admissions open at both of our campuses.",
        "source": {
            "new": {
                "provider": "first_party_website",
                "source_url": "https://crescent-valley.example/admissions",
                "storage_class": "full_allowed",
                "observed_at": observed,
                "expires_at": (clock.now() + timedelta(days=90)).isoformat(),
            }
        },
        **overrides,
    }


def count(app: FastAPI, model: type[Any]) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.fixture
def restarted(app_settings: Settings, team: Team) -> Iterator[TestClient]:
    """A second app instance (fresh process state) over the same database: simulates an API restart."""
    second = create_app(app_settings, clock=team.app.state.clock)
    client = TestClient(second, raise_server_exceptions=False)
    client.cookies = team.clients[Role.OWNER].cookies
    yield client
    close_app(second)


# --- ACCOUNT-01 ------------------------------------------------------------------------------------


def test_operator_creates_account_and_list_and_detail_agree(team: Team) -> None:
    response = team.send(
        Role.OPERATOR,
        "POST",
        BASE,
        {"canonical_name": "Crescent Valley Grammar School (Synthetic)", "locality": "Johar Town"},
    )
    assert response.status_code == 201
    created = response.json()
    uuid.UUID(created["id"])
    assert (created["version"], created["city"], created["status"]) == (1, "Lahore", "discovered")
    assert response.headers["etag"] == '"1"'
    listed = team.get(Role.OBSERVER, BASE).json()
    assert [a["id"] for a in listed["accounts"]] == [created["id"]] and listed["next_cursor"] is None
    detail = team.get(Role.OBSERVER, f"{BASE}/{created['id']}").json()
    assert {k: detail[k] for k in created} == created
    assert [a["action_type"] for a in detail["audits"]] == ["account.created"]
    assert detail["audits"][0]["actor_user_id"] == str(team.user_ids[Role.OPERATOR])


def test_two_schools_with_the_same_name_stay_separate(team: Team) -> None:
    first = team.create(locality="Johar Town")
    second = team.create(locality="DHA Phase 5")
    assert first["id"] != second["id"] and first["normalized_name"] == second["normalized_name"]
    assert len(team.get(Role.OWNER, BASE, q="crescent valley").json()["accounts"]) == 2


# --- ACCOUNT-02 / ACCOUNT-03 -------------------------------------------------------------------------


def test_source_supported_fact_with_new_source_persists_after_restart(team: Team, restarted: TestClient) -> None:
    account = team.create()
    added = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", supported_fact(team))
    assert added.status_code == 201, added.text
    [fact] = restarted.get(f"{BASE}/{account['id']}").json()["facts"]
    assert fact["id"] == added.json()["id"]
    assert (fact["claim_type"], fact["value"], fact["verification_status"]) == (
        "campus_count",
        {"count": 2},
        "source_supported",
    )
    assert fact["is_stale"] is False and fact["is_current"] is True
    assert fact["source"]["provider"] == "first_party_website"
    assert fact["source"]["source_url"] == "https://crescent-valley.example/admissions"
    assert fact["source"]["permitted_storage_class"] == "full_allowed"
    assert fact["source"]["rights_policy_version"].startswith("rights-")
    assert fact["observed_at"] == fact["source"]["observed_at"]
    assert fact["recorded_by"] == str(team.user_ids[Role.OPERATOR])
    assert count(team.app, SourceRecord) == 1


def test_unknown_erp_is_a_visible_hypothesis_not_absence(team: Team) -> None:
    account = team.create()
    hypothesis = {
        "claim_type": "software_in_use",
        "value": {"status": "unknown"},
        "verification_status": "hypothesis",
        "confidence_label": "unknown",
        "observed_at": now(team),
    }
    assert team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", hypothesis).status_code == 201
    [fact] = team.get(Role.OWNER, f"{BASE}/{account['id']}").json()["facts"]
    assert (fact["verification_status"], fact["confidence_label"], fact["source"]) == ("hypothesis", "unknown", None)
    assert fact["value"] == {"status": "unknown", "product": None}  # normalized by the typed claim model
    negative = {**hypothesis, "value": {"status": "none"}}
    assert team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", negative).status_code == 400
    claimed_absence = {**hypothesis, "verification_status": "source_supported", "confidence_label": "strong"}
    assert team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", claimed_absence).status_code == 400
    assert count(team.app, AccountFact) == 1


# --- ACCOUNT-04 ------------------------------------------------------------------------------------


def test_correction_keeps_history_links_successor_and_is_unambiguous(team: Team, app_settings: Settings) -> None:
    account = team.create()
    original = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", supported_fact(team)).json()["id"]
    correction = {
        **supported_fact(team, value={"count": 3}, evidence_excerpt="Our third campus opened this term."),
        "reason": "School website lists a third campus in Bahria Town",
    }
    corrected = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts/{original}/corrections", correction)
    assert corrected.status_code == 201, corrected.text
    successor = corrected.json()["id"]

    facts = {f["id"]: f for f in team.get(Role.OBSERVER, f"{BASE}/{account['id']}").json()["facts"]}
    assert facts[original]["is_current"] is False and facts[original]["superseded_by_fact_id"] == successor
    assert facts[original]["value"] == {"count": 2}  # history retained verbatim
    assert facts[successor]["is_current"] is True and facts[successor]["supersedes_fact_id"] == original
    assert facts[successor]["correction_reason"] == "School website lists a third campus in Bahria Town"
    assert [f["value"] for f in facts.values() if f["is_current"] and f["claim_type"] == "campus_count"] == [
        {"count": 3}
    ]

    for sql in (
        "UPDATE account_facts SET typed_value_json = '{\"count\": 9}' WHERE id = %(id)s",
        "DELETE FROM account_facts WHERE id = %(id)s",
        "UPDATE action_audits SET action_type = 'account.nothing' WHERE target_id = %(account)s",
    ):
        with (
            psycopg.connect(str(app_settings.database_url), autocommit=True) as conn,
            pytest.raises(psycopg.errors.CheckViolation, match="append-only"),
        ):
            conn.execute(sql, {"id": original, "account": account["id"]})
    audits = [a["action_type"] for a in team.get(Role.OWNER, f"{BASE}/{account['id']}").json()["audits"]]
    assert sorted(audits) == ["account.created", "account.fact_added", "account.fact_corrected"]


def test_correction_requires_reason_and_same_claim_type(team: Team) -> None:
    account = team.create()
    original = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", supported_fact(team)).json()["id"]
    path = f"{BASE}/{account['id']}/facts/{original}/corrections"
    assert team.send(Role.OPERATOR, "POST", path, supported_fact(team)).status_code == 422  # no reason
    assert team.send(Role.OPERATOR, "POST", path, {**supported_fact(team), "reason": "x"}).status_code == 422
    other_type = {
        "claim_type": "website_presence",
        "value": {"status": "present"},
        "verification_status": "hypothesis",
        "confidence_label": "weak",
        "observed_at": now(team),
        "reason": "Wrong claim entirely",
    }
    assert team.send(Role.OPERATOR, "POST", path, other_type).status_code == 422
    assert count(team.app, AccountFact) == 1


# --- ACCOUNT-05 ------------------------------------------------------------------------------------


def test_concurrent_patches_one_winner_and_stale_patch_preserves_state(team: Team) -> None:
    account = team.create()
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def rename(role: Role, name: str) -> None:
        barrier.wait()
        results[name] = team.send(
            role, "PATCH", f"{BASE}/{account['id']}", {"expected_version": 1, "canonical_name": name}
        ).status_code

    threads = [
        threading.Thread(target=rename, args=(Role.OWNER, "Owner Rename (Synthetic)")),
        threading.Thread(target=rename, args=(Role.OPERATOR, "Operator Rename (Synthetic)")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()) == [200, 409]
    winner = next(name for name, status in results.items() if status == 200)
    detail = team.get(Role.OWNER, f"{BASE}/{account['id']}").json()
    assert (detail["canonical_name"], detail["version"]) == (winner, 2)
    stale = team.send(Role.OWNER, "PATCH", f"{BASE}/{account['id']}", {"expected_version": 1, "locality": "Gulberg"})
    assert stale.status_code == 409 and "reload and retry" in stale.json()["error"]["message"]
    after = team.get(Role.OWNER, f"{BASE}/{account['id']}").json()
    assert (after["locality"], after["version"]) == ("Johar Town", 2)
    assert [a["action_type"] for a in after["audits"]].count("account.updated") == 1


def test_double_correction_has_exactly_one_successor(team: Team) -> None:
    account = team.create()
    original = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", supported_fact(team)).json()["id"]
    path = f"{BASE}/{account['id']}/facts/{original}/corrections"
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def correct(role: Role, n: int) -> None:
        barrier.wait()
        body = {**supported_fact(team, value={"count": n}), "reason": f"Correcting to {n} campuses"}
        statuses.append(team.send(role, "POST", path, body).status_code)

    threads = [
        threading.Thread(target=correct, args=(Role.OWNER, 3)),
        threading.Thread(target=correct, args=(Role.OPERATOR, 4)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [201, 409]
    facts = team.get(Role.OWNER, f"{BASE}/{account['id']}").json()["facts"]
    assert len([f for f in facts if f["supersedes_fact_id"] == original]) == 1
    assert len([f for f in facts if f["is_current"]]) == 1
    assert (
        team.send(Role.OWNER, "POST", path, {**supported_fact(team), "reason": "Correct the old one again"}).status_code
        == 409
    )


def test_if_match_header_is_an_alternative_to_expected_version(team: Team) -> None:
    account = team.create()
    ok = team.send(Role.OPERATOR, "PATCH", f"{BASE}/{account['id']}", {"locality": "Gulberg"}, **{"If-Match": '"1"'})
    assert ok.status_code == 200 and ok.headers["etag"] == '"2"'
    disagree = team.send(
        Role.OPERATOR,
        "PATCH",
        f"{BASE}/{account['id']}",
        {"expected_version": 2, "locality": "X"},
        **{"If-Match": '"5"'},
    )
    assert disagree.status_code == 400
    missing = team.send(Role.OPERATOR, "PATCH", f"{BASE}/{account['id']}", {"locality": "X"})
    assert missing.status_code == 400 and "expected_version" in missing.json()["error"]["message"]


# --- ACCOUNT-06 ------------------------------------------------------------------------------------


def test_role_matrix_and_csrf_with_no_persisted_writes(team: Team) -> None:
    account = team.create()
    fact_path = f"{BASE}/{account['id']}/facts"
    observer_writes = [
        team.send(Role.OBSERVER, "POST", BASE, {"canonical_name": "Observer School (Synthetic)"}),
        team.send(Role.OBSERVER, "PATCH", f"{BASE}/{account['id']}", {"expected_version": 1, "locality": "X"}),
        team.send(Role.OBSERVER, "POST", fact_path, supported_fact(team)),
        team.send(Role.OBSERVER, "POST", f"{BASE}/{account['id']}/archive", {"expected_version": 1}),
    ]
    assert [r.status_code for r in observer_writes] == [403, 403, 403, 403]
    assert (
        team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/archive", {"expected_version": 1}).status_code == 403
    )
    operator = team.clients[Role.OPERATOR]
    no_csrf = operator.post(fact_path, json=supported_fact(team), headers=ORIGIN)
    assert no_csrf.status_code == 403
    anonymous = TestClient(team.app, raise_server_exceptions=False)
    assert anonymous.get(BASE).status_code == 401
    assert anonymous.post(BASE, json={"canonical_name": "Anon"}, headers=ORIGIN).status_code == 401
    assert (count(team.app, Account), count(team.app, AccountFact), count(team.app, SourceRecord)) == (1, 0, 0)
    detail = team.get(Role.OBSERVER, f"{BASE}/{account['id']}")
    assert detail.status_code == 200 and detail.json()["version"] == 1
    archived = team.send(Role.OWNER, "POST", f"{BASE}/{account['id']}/archive", {"expected_version": 1})
    assert archived.status_code == 200 and archived.json()["status"] == "excluded"
    again = team.send(Role.OWNER, "POST", f"{BASE}/{account['id']}/archive", {"expected_version": 2})
    assert again.status_code == 409


# --- ACCOUNT-07 ------------------------------------------------------------------------------------


def test_cross_org_accounts_facts_and_sources_are_invisible(team: Team) -> None:
    mine = team.create()
    my_fact = team.send(Role.OPERATOR, "POST", f"{BASE}/{mine['id']}/facts", supported_fact(team)).json()["id"]
    my_source = team.get(Role.OWNER, f"{BASE}/{mine['id']}").json()["facts"][0]["source"]["id"]

    other_org = add_organization(team.app, "Other Org")
    add_user(team.app, other_org, "intruder@other.example", role=Role.OWNER)
    intruder = TestClient(team.app, raise_server_exceptions=False)
    csrf = logged_in(intruder, "intruder@other.example")
    theirs = intruder.post(
        BASE, json={"canonical_name": "Their School (Synthetic)"}, headers=mutation_headers(csrf)
    ).json()

    assert intruder.get(BASE).json()["accounts"] == [theirs]
    probes = [
        intruder.get(f"{BASE}/{mine['id']}"),
        intruder.patch(
            f"{BASE}/{mine['id']}", json={"expected_version": 1, "locality": "X"}, headers=mutation_headers(csrf)
        ),
        intruder.post(f"{BASE}/{mine['id']}/facts", json=supported_fact(team), headers=mutation_headers(csrf)),
        intruder.post(
            f"{BASE}/{theirs['id']}/facts/{my_fact}/corrections",
            json={**supported_fact(team), "reason": "Hijack attempt"},
            headers=mutation_headers(csrf),
        ),
        intruder.post(
            f"{BASE}/{theirs['id']}/facts",
            json=supported_fact(team, source={"source_id": my_source}),
            headers=mutation_headers(csrf),
        ),
        intruder.post(f"{BASE}/{mine['id']}/archive", json={"expected_version": 1}, headers=mutation_headers(csrf)),
    ]
    assert [p.status_code for p in probes] == [404] * 6
    assert all(mine["canonical_name"] not in p.text for p in probes)
    assert team.get(Role.OWNER, f"{BASE}/{mine['id']}").json()["version"] == 1
    with db(team.app) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(AccountFact).where(AccountFact.organization_id == other_org)
            )
            == 0
        )


# --- ACCOUNT-08 ------------------------------------------------------------------------------------


def test_invalid_listing_parameters_are_typed_errors(team: Team) -> None:
    team.create()
    cases: list[tuple[dict[str, Any], int]] = [
        ({"limit": 0}, 422),
        ({"limit": 101}, 422),
        ({"status": "deleted"}, 422),
        ({"city": "Karachi"}, 422),
        ({"vertical_id": "not-a-uuid"}, 422),
        ({"cursor": "garbage!!"}, 400),
        ({"cursor": "x" * 600}, 422),
        ({"q": "%%%"}, 400),
    ]
    for params, status in cases:
        response = team.get(Role.OWNER, BASE, **params)
        assert response.status_code == status, params
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR" and error["request_id"] == response.headers["x-request-id"]


def test_bad_transitions_and_forbidden_or_stale_sources_write_nothing(team: Team, clock: FixedClock) -> None:
    account = team.create()
    path = f"{BASE}/{account['id']}"
    skip = team.send(Role.OPERATOR, "PATCH", path, {"expected_version": 1, "status": "shortlisted"})
    assert skip.status_code == 422 and "cannot change from discovered to shortlisted" in skip.json()["error"]["message"]
    exclude = team.send(Role.OPERATOR, "PATCH", path, {"expected_version": 1, "status": "excluded"})
    assert exclude.status_code == 422
    places_content = supported_fact(
        team,
        source={
            "new": {
                "provider": "google_places",
                "source_url": "https://maps.example/place/1",
                "storage_class": "full_allowed",
                "observed_at": now(team),
                "external_key": "ChIJ-synthetic",
            }
        },
    )
    rights = team.send(Role.OPERATOR, "POST", f"{path}/facts", places_content)
    assert rights.status_code == 403 and "do not permit" in rights.json()["error"]["message"]
    private_url = supported_fact(team)
    private_url["source"]["new"]["source_url"] = "http://169.254.169.254/latest/meta-data"
    assert team.send(Role.OPERATOR, "POST", f"{path}/facts", private_url).status_code == 400
    expiring = supported_fact(team)
    expiring["source"]["new"]["expires_at"] = (clock.now() + timedelta(hours=2)).isoformat()
    assert team.send(Role.OPERATOR, "POST", f"{path}/facts", expiring).status_code == 201
    source_id = team.get(Role.OWNER, path).json()["facts"][0]["source"]["id"]
    clock.advance(timedelta(hours=3))  # past the source TTL, well within the session lifetime
    stale = team.send(Role.OPERATOR, "POST", f"{path}/facts", supported_fact(team, source={"source_id": source_id}))
    assert stale.status_code == 400 and "expired" in stale.json()["error"]["message"]
    detail = team.get(Role.OWNER, path).json()
    assert (detail["status"], detail["version"]) == ("discovered", 1)
    assert [f["is_stale"] for f in detail["facts"]] == [True]
    assert (count(team.app, AccountFact), count(team.app, SourceRecord)) == (1, 1)


def test_failed_inline_source_rolls_back_with_the_fact(team: Team) -> None:
    account = team.create()
    body = supported_fact(team, evidence_excerpt="x" * 999 + "\u0000")
    assert team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", body).status_code == 400
    assert (count(team.app, AccountFact), count(team.app, SourceRecord)) == (0, 0)
    assert [a["action_type"] for a in team.get(Role.OWNER, f"{BASE}/{account['id']}").json()["audits"]] == [
        "account.created"
    ]


# --- pagination --------------------------------------------------------------------------------------


def test_keyset_pagination_is_complete_stable_and_filter_bound(team: Team, clock: FixedClock) -> None:
    ids = []
    for i in range(7):
        clock.advance(timedelta(seconds=1))
        ids.append(team.create(name=f"School {i:02d} (Synthetic)")["id"])
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = team.get(Role.OWNER, BASE, **params).json()
        seen += [a["id"] for a in body["accounts"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and seen == list(reversed(ids))
    first = team.get(Role.OWNER, BASE, limit=3).json()
    changed = team.get(Role.OWNER, BASE, limit=3, status="discovered", cursor=first["next_cursor"])
    assert changed.status_code == 400 and "restart from the first page" in changed.json()["error"]["message"]
    prefixed = team.get(Role.OWNER, BASE, q="school 0").json()["accounts"]
    assert len(prefixed) == 7
    assert team.get(Role.OWNER, BASE, q="nothing like this").json()["accounts"] == []


def test_cursor_from_another_organization_is_rejected(team: Team) -> None:
    for i in range(3):
        team.create(name=f"School {i} (Synthetic)")
    cursor = team.get(Role.OWNER, BASE, limit=1).json()["next_cursor"]
    other_org = add_organization(team.app, "Other Org")
    add_user(team.app, other_org, "other@other.example")
    other = TestClient(team.app, raise_server_exceptions=False)
    logged_in(other, "other@other.example")
    assert other.get(BASE, params={"limit": 1, "cursor": cursor}).status_code == 400


# --- ACCOUNT-09 ------------------------------------------------------------------------------------


def test_markup_long_and_unicode_names_are_bounded_and_returned_as_data(team: Team) -> None:
    hostile = '<script>alert("x")</script> School (Synthetic)'
    created = team.create(name=hostile)
    detail = team.get(Role.OWNER, f"{BASE}/{created['id']}")
    assert detail.headers["content-type"].startswith("application/json")
    assert detail.json()["canonical_name"] == hostile
    urdu = team.create(name="دی لاہور گرامر اسکول (Synthetic)")
    assert urdu["canonical_name"] == "دی لاہور گرامر اسکول (Synthetic)"
    too_long = team.send(Role.OPERATOR, "POST", BASE, {"canonical_name": "x" * 251})
    assert too_long.status_code == 422
    bidi = team.send(Role.OPERATOR, "POST", BASE, {"canonical_name": "School‮loohcS"})
    assert bidi.status_code == 400
    long_excerpt = supported_fact(team, evidence_excerpt="y" * 1001)
    assert team.send(Role.OPERATOR, "POST", f"{BASE}/{created['id']}/facts", long_excerpt).status_code == 422
    assert count(team.app, Account) == 2


# --- ACCOUNT-10 / failure paths --------------------------------------------------------------------


def test_everything_survives_a_restart(team: Team, restarted: TestClient) -> None:
    account = team.create()
    original = team.send(Role.OPERATOR, "POST", f"{BASE}/{account['id']}/facts", supported_fact(team)).json()["id"]
    team.send(
        Role.OPERATOR,
        "POST",
        f"{BASE}/{account['id']}/facts/{original}/corrections",
        {**supported_fact(team, value={"count": 3}), "reason": "Third campus confirmed"},
    )
    team.send(Role.OPERATOR, "PATCH", f"{BASE}/{account['id']}", {"expected_version": 1, "status": "researching"})
    detail = restarted.get(f"{BASE}/{account['id']}").json()
    assert (detail["status"], detail["version"]) == ("researching", 2)
    assert len(detail["facts"]) == 2 and len([f for f in detail["facts"] if f["is_current"]]) == 1
    assert len(detail["audits"]) == 4
    with db(team.app) as session:
        assert session.scalar(select(func.count()).select_from(ActionAudit)) == 4


def test_database_outage_is_a_safe_503(team: Team, app_settings: Settings) -> None:
    down = create_app(
        app_settings.model_copy(update={"database_url": "postgresql://u:db-secret-value@127.0.0.1:1/x_test"}),
        clock=team.app.state.clock,
    )
    client = TestClient(down, raise_server_exceptions=False)
    client.cookies = team.clients[Role.OWNER].cookies
    response = client.get(BASE)
    assert response.status_code == 503 and "db-secret-value" not in response.text
    close_app(down)


def test_cas_rejects_a_write_that_lands_between_read_and_update(
    team: Team, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic race: a competing commit happens after the service read the row, before its UPDATE."""
    account = team.create()
    from app.accounts import service as account_service

    original = account_service._account

    raced: list[bool] = []

    def read_then_race(db: Any, actor: Any, account_id: uuid.UUID) -> Account:
        row: Account = original(db, actor, account_id)
        if raced:  # race exactly once, on the first read
            return row
        raced.append(True)
        with psycopg.connect(str(app_settings.database_url), autocommit=True) as conn:
            conn.execute(
                "UPDATE accounts SET canonical_name = 'Racer Rename (Synthetic)', version = version + 1 WHERE id = %s",
                (account_id,),
            )
        return row

    monkeypatch.setattr(account_service, "_account", read_then_race)
    response = team.send(
        Role.OPERATOR, "PATCH", f"{BASE}/{account['id']}", {"expected_version": 1, "locality": "Gulberg"}
    )
    monkeypatch.undo()
    assert response.status_code == 409
    detail = team.get(Role.OWNER, f"{BASE}/{account['id']}").json()
    assert (detail["canonical_name"], detail["locality"], detail["version"]) == (
        "Racer Rename (Synthetic)",
        "Johar Town",
        2,
    )
