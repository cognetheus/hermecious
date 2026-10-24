"""P2.1 acceptance: SOURCE-01..SOURCE-10 (offline synthetic fixture, real Postgres)."""

import json
import os
import socket
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text

from app.accounts import service as source_service
from app.accounts.models import Account, ActionAudit, SourceRecord
from app.auth.models import Role
from app.auth.service import Actor
from app.core.clock import FixedClock
from app.core.errors import NotFound
from app.core.settings import Settings
from app.discovery import registry
from app.discovery.contracts import Operation, SourceQuery
from app.discovery.fixture import FixtureFaults, FixtureLahoreSchoolsAdapter
from app.discovery.runner import DiscoveryBudget, DiscoveryFixtureReport, run_discovery
from tests.integration.auth_helpers import add_organization, add_user, db
from tests.integration.db import API_ROOT

Logs = Callable[[], list[dict[str, Any]]]
LAHORE = SourceQuery(city="Lahore", vertical_slug="schools")
RAW_RESTRICTED = ("RESTRICTED-RAW-TEXT-2", "RESTRICTED-RAW-TEXT-3", "grant marketing consent")


@pytest.fixture(autouse=True)
def no_egress(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """Records every outbound connection that is not the test Postgres/Redis; tests assert it stays empty."""
    allowed_ports = {5432, 6379}
    attempts: list[Any] = []
    original = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        if port not in allowed_ports:
            attempts.append(address)
            raise OSError("egress blocked by test guard")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield attempts
    assert attempts == [], f"unexpected network egress: {attempts}"


def make_actor(app: FastAPI, name: str = "Discovery Org", email: str = "owner@discovery.example") -> Actor:
    org = add_organization(app, name)
    user = add_user(app, org, email, role=Role.OWNER)
    return Actor(user_id=user, organization_id=org, role=Role.OWNER, session_id=uuid.uuid4(), verifier="unused")


def run(
    app: FastAPI,
    actor: Actor,
    *,
    adapter: FixtureLahoreSchoolsAdapter | None = None,
    query: SourceQuery = LAHORE,
    budget: DiscoveryBudget | None = None,
    persist: bool = True,
    monotonic: Callable[[], float] | None = None,
) -> DiscoveryFixtureReport:
    with db(app) as session:
        kwargs: dict[str, Any] = {"monotonic": monotonic} if monotonic else {}
        return run_discovery(
            session,
            actor=actor,
            clock=app.state.clock,
            environment="test",
            adapter=adapter or FixtureLahoreSchoolsAdapter(),
            query=query,
            budget=budget,
            persist=persist,
            **kwargs,
        )


def sources(app: FastAPI, actor: Actor | None = None) -> list[SourceRecord]:
    with db(app) as session:
        query = select(SourceRecord).order_by(SourceRecord.external_key)
        if actor:
            query = query.where(SourceRecord.organization_id == actor.organization_id)
        return list(session.scalars(query))


def count(app: FastAPI, model: type[Any]) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def with_descriptor(**changes: Any) -> FixtureLahoreSchoolsAdapter:
    base = registry.DESCRIPTORS[registry.FIXTURE_PROVIDER]
    return FixtureLahoreSchoolsAdapter(descriptor=base.model_copy(update=changes))


# --- SOURCE-01 / SOURCE-02 ----------------------------------------------------------------------


def test_fixture_search_is_bounded_typed_offline_and_labelled_synthetic(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter()
    report = run(app, actor, adapter=adapter)
    assert report.label.startswith("SYNTHETIC FIXTURE DATA")
    assert (report.provider, report.adapter_version, report.rights_policy_version) == (
        "fixture_lahore_schools",
        "1.0.0",
        "fixture-synthetic-2026-10",
    )
    assert (report.stop_reason, report.examined_count) == ("completed", 9)
    assert report.budget_consumed["search_pages"] == 3 and adapter.search_calls == 3
    assert sorted(p.external_key for p in report.candidates) == [
        "cvg-dha-phase-5",
        "cvg-johar-town",
        "gulberg-science",
        "model-town-montessori",
        "ravi-bank-shahdara",
    ]
    assert all(p.status == "unverified" for p in report.candidates)
    assert report.rejection_reasons == {
        "expired_observation": 1,
        "not_persisted_missing_url": 1,
        "query_mismatch": 1,
        "unapproved_host": 1,
        "unsafe_url": 1,
    }
    assert (report.accepted_count, report.persisted_count) == (5, 4)
    assert count(app, Account) == 0  # discovery never creates or merges accounts


def test_fetched_observations_record_rights_and_ttl_provenance(app: FastAPI, clock: FixedClock) -> None:
    actor = make_actor(app)
    run(app, actor)
    rows = {r.external_key: r for r in sources(app, actor)}
    assert set(rows) == {
        "fixture_lahore_schools:cvg-dha-phase-5",
        "fixture_lahore_schools:cvg-johar-town",
        "fixture_lahore_schools:gulberg-science",
        "fixture_lahore_schools:ravi-bank-shahdara",
    }
    johar = rows["fixture_lahore_schools:cvg-johar-town"]
    assert (johar.provider, johar.permitted_storage_class, johar.rights_policy_version) == (
        "fixture_lahore_schools",
        "full_allowed",
        "fixture-synthetic-2026-10",
    )
    assert johar.source_url == "https://school.fixture.example/record/1"
    assert johar.expires_at == johar.observed_at + timedelta(days=30)  # clamped to descriptor retention TTL
    assert johar.source_payload_reference is None  # provenance only, never content
    assert rows["fixture_lahore_schools:ravi-bank-shahdara"].permitted_storage_class == "derived_only"
    assert rows["fixture_lahore_schools:cvg-dha-phase-5"].permitted_storage_class == "metadata_only"


# --- SOURCE-03 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"enabled": False}, "provider_disabled"),
        ({"terms_reference": None}, "provider_unreviewed"),
        ({"rights_policy_version": None}, "provider_unreviewed"),
        ({"last_reviewed_at": None}, "provider_unreviewed"),
        ({"source_kind": "website"}, "live_sources_not_enabled"),
        ({"environments": frozenset({"production"})}, "provider_not_enabled_in_environment"),
        ({"requires_credentials": True}, "credentials_not_supported"),
        ({"permitted_operations": frozenset({Operation.FETCH})}, "operation_not_licensed:search"),
        ({"permitted_operations": frozenset({Operation.SEARCH})}, "operation_not_licensed:fetch"),
    ],
    ids=["disabled", "no-terms", "no-rights", "unreviewed", "live-kind", "env", "credentials", "no-search", "no-fetch"],
)
def test_policy_refusals_happen_before_the_adapter_runs(app: FastAPI, changes: dict[str, Any], reason: str) -> None:
    actor = make_actor(app)
    adapter = with_descriptor(**changes)
    with pytest.raises(registry.SourcePolicyError, match=reason):
        run(app, actor, adapter=adapter)
    assert (adapter.search_calls, adapter.fetch_calls) == (0, 0)
    assert sources(app) == []


def test_unknown_provider_is_refused() -> None:
    with pytest.raises(registry.SourcePolicyError, match="unknown_provider"):
        registry.resolve("google_maps_scraper", "test")


# --- SOURCE-04 -----------------------------------------------------------------------------------------


def test_each_storage_class_keeps_only_permitted_content(app: FastAPI, json_logs: Logs, app_settings: Settings) -> None:
    actor = make_actor(app)
    report = run(app, actor)
    previews = {p.external_key: p for p in report.candidates}
    full, derived, metadata = previews["cvg-johar-town"], previews["ravi-bank-shahdara"], previews["cvg-dha-phase-5"]
    assert (full.excerpt, full.claim_hints) == (
        "Admissions open at both of our campuses.",
        ["page mentions two campuses"],
    )
    assert (derived.excerpt, derived.claim_hints) == (None, ["website present"])
    assert (metadata.excerpt, metadata.claim_hints) == (None, [])
    dumped = report.model_dump_json() + json.dumps(json_logs())
    with db(app) as session:
        dumped += json.dumps([list(map(str, r)) for r in session.execute(text("SELECT * FROM source_records")).all()])
        dumped += json.dumps([str(a.details_json) for a in session.scalars(select(ActionAudit))])
    for restricted in RAW_RESTRICTED:
        assert restricted not in dumped


def test_descriptor_storage_ceiling_rejects_richer_rights(app: FastAPI) -> None:
    actor = make_actor(app)
    report = run(app, actor, adapter=with_descriptor(max_storage_class="metadata_only"))
    # full_allowed (2, incl. the stale one: rights are checked before freshness) + derived_only (1)
    assert report.rejection_reasons["rights_denied"] == 3
    assert {r.permitted_storage_class for r in sources(app, actor)} == {"metadata_only"}


# --- SOURCE-05 -----------------------------------------------------------------------------------------


def test_thirty_one_plus_candidates_are_capped_at_thirty(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter(
        descriptor=registry.DESCRIPTORS[registry.FIXTURE_PROVIDER].model_copy(update={"page_size": 10}),
        faults=FixtureFaults(extra_records=40),
    )
    report = run(app, actor, adapter=adapter, persist=False)
    assert report.stop_reason == "candidate_cap"
    assert report.accepted_count + report.rejection_reasons.get("expired_observation", 0) <= 30
    assert report.budget_consumed["search_pages"] <= 5


@pytest.mark.parametrize(
    ("faults", "reason", "stop"),
    [
        (FixtureFaults(repeat_cursor=True), "cursor_cycle", "cursor_cycle"),
        (FixtureFaults(duplicate_first=True), "duplicate_key", "completed"),
        (FixtureFaults(oversize_by=5), "page_oversized", "completed"),
    ],
    ids=["repeated-cursor", "duplicate-keys", "oversized-page"],
)
def test_misbehaving_pagination_is_bounded_and_deterministic(
    app: FastAPI, faults: FixtureFaults, reason: str, stop: str
) -> None:
    actor = make_actor(app)
    first = run(app, actor, adapter=FixtureLahoreSchoolsAdapter(faults=faults), persist=False)
    second = run(app, actor, adapter=FixtureLahoreSchoolsAdapter(faults=faults), persist=False)
    assert first.stop_reason == stop and reason in first.rejection_reasons
    assert first.budget_consumed["search_pages"] <= 5

    def strip(report: DiscoveryFixtureReport) -> dict[str, Any]:
        return report.model_dump(exclude={"run_id", "budget_consumed"})

    assert strip(first) == strip(second)


# --- SOURCE-06 ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [SourceQuery(city="Karachi", vertical_slug="schools"), SourceQuery(city="Lahore", vertical_slug="retail")],
    ids=["wrong-city", "wrong-vertical"],
)
def test_unsupported_queries_are_refused_not_answered_with_nearby_data(app: FastAPI, query: SourceQuery) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter()
    with pytest.raises(registry.SourcePolicyError, match="unsupported_query"):
        run(app, actor, adapter=adapter, query=query)
    assert adapter.search_calls == 0


def test_malformed_records_are_rejected_individually(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter(
        descriptor=registry.DESCRIPTORS[registry.FIXTURE_PROVIDER].model_copy(update={"page_size": 15}),
        faults=FixtureFaults(malformed=True),
    )
    report = run(app, actor, adapter=adapter, persist=False)
    assert report.rejection_reasons["invalid_record"] >= 2  # naive timestamp, non-string name, no observed_at
    assert report.rejection_reasons.get("unsafe_url", 0) >= 2  # metadata IP + fragment URL
    assert report.accepted_count == 5 and count(app, Account) == 0


@pytest.mark.parametrize(
    "bad",
    [{"city": ""}, {"keywords": ["x" * 41]}, {"keywords": ["drop table;--"]}, {"keywords": ["a"] * 6}],
    ids=["empty-city", "long-keyword", "unsafe-keyword", "too-many-keywords"],
)
def test_query_validation(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SourceQuery.model_validate({"city": "Lahore", "vertical_slug": "schools", **bad})


# --- SOURCE-07 ------------------------------------------------------------------------------------------


class FakeMonotonic:
    def __init__(self, step: float) -> None:
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        return self.now

    def tick(self) -> None:
        self.now += self.step


@pytest.mark.parametrize(
    ("budget", "stop", "consumed_key", "limit"),
    [
        (DiscoveryBudget(max_search_pages=1), "page_cap", "search_pages", 1),
        (DiscoveryBudget(max_fetches=2), "fetch_cap", "fetches", 2),
        (DiscoveryBudget(max_cost_units=1), "cost_cap", "cost_units", 1),
    ],
    ids=["pages", "fetches", "cost"],
)
def test_budget_caps_stop_with_truthful_partial_report(
    app: FastAPI, budget: DiscoveryBudget, stop: str, consumed_key: str, limit: int
) -> None:
    actor = make_actor(app)
    report = run(app, actor, budget=budget, persist=False)
    assert report.stop_reason == stop
    assert report.budget_consumed[consumed_key] == limit
    assert report.accepted_count <= report.examined_count


def test_time_cap_uses_the_injected_clock(app: FastAPI) -> None:
    actor = make_actor(app)
    fake = FakeMonotonic(step=25.0)
    adapter = FixtureLahoreSchoolsAdapter(faults=FixtureFaults(on_call=fake.tick))
    report = run(app, actor, adapter=adapter, monotonic=fake, persist=False)
    assert report.stop_reason == "time_cap"
    assert report.budget_consumed["seconds"] >= 50.0


def test_transient_429_is_retried_within_budget(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter(faults=FixtureFaults(rate_limited_calls=frozenset({1})))
    report = run(app, actor, adapter=adapter, persist=False)
    assert report.stop_reason == "completed" and report.budget_consumed["retries"] == 1
    assert report.rejection_reasons["search_rate_limited"] == 1 and report.accepted_count == 5


def test_persistent_429_stops_without_over_budget_retry(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter(faults=FixtureFaults(rate_limited_calls=frozenset({1, 2, 3, 4, 5})))
    report = run(app, actor, adapter=adapter, persist=False)
    assert report.stop_reason == "rate_limited"
    assert report.budget_consumed["retries"] == 2 and adapter.search_calls == 3
    assert report.accepted_count == 0


def test_fetch_timeout_skips_one_record_and_continues(app: FastAPI) -> None:
    actor = make_actor(app)
    adapter = FixtureLahoreSchoolsAdapter(faults=FixtureFaults(fetch_timeout_keys=frozenset({"cvg-johar-town"})))
    report = run(app, actor, adapter=adapter, persist=False)
    assert report.rejection_reasons["fetch_timeout"] == 1
    assert "cvg-johar-town" not in {p.external_key for p in report.candidates} and report.accepted_count == 4


def test_budgets_can_only_be_lowered() -> None:
    for field, value in [("max_candidates", 31), ("max_search_pages", 6), ("max_fetches", 21), ("max_seconds", 61)]:
        with pytest.raises(ValueError, match=field):
            DiscoveryBudget(**{field: value})


# --- SOURCE-08 -------------------------------------------------------------------------------------------


def test_unsafe_urls_and_prompt_injection_are_inert_data(app: FastAPI, no_egress: list[Any]) -> None:
    actor = make_actor(app)
    report = run(app, actor)
    assert report.rejection_reasons["unsafe_url"] == 1 and report.rejection_reasons["unapproved_host"] == 1
    gulberg = next(p for p in report.candidates if p.external_key == "gulberg-science")
    assert gulberg.status == "unverified" and gulberg.claim_hints == []  # metadata_only: hints not retained
    assert count(app, Account) == 0  # "create an account" instruction had no effect
    assert no_egress == []
    blob = report.model_dump_json()
    assert "169.254.169.254" not in blob and "evil.example" not in blob


def test_discovery_package_has_no_network_client_imports() -> None:
    """P2.2/P2.4: the only egress is app.egress, and only the reviewed OSM adapter module may use it."""
    package = API_ROOT / "app" / "discovery"
    forbidden = ("import socket", "import ssl", "http.client", "import httpx", "import requests", "urllib.request",
                 "import aiohttp")  # fmt: skip
    offenders = [
        f"{path.name}: {needle}" for path in package.rglob("*.py") for needle in forbidden if needle in path.read_text()
    ]
    assert offenders == []
    egress_users = sorted(p.name for p in package.rglob("*.py") if "app.egress" in p.read_text())
    assert egress_users == ["osm.py"]
    network_modules = sorted(
        str(p.relative_to(API_ROOT))
        for p in (API_ROOT / "app").rglob("*.py")
        if any(n in p.read_text() for n in ("http.client", "import ssl", "urllib.request", "import httpx"))
    )
    assert network_modules == ["app/egress/https_client.py"]


# --- SOURCE-09 ---------------------------------------------------------------------------------------------


def test_two_organizations_get_isolated_provenance_and_replay_is_idempotent(app: FastAPI) -> None:
    org_a = make_actor(app, "Org A", "a@discovery.example")
    org_b = make_actor(app, "Org B", "b@discovery.example")
    first_a, first_b = run(app, org_a), run(app, org_b)
    assert first_a.persisted_count == first_b.persisted_count == 4
    keys_a = {r.external_key for r in sources(app, org_a)}
    assert keys_a == {r.external_key for r in sources(app, org_b)} and len(sources(app)) == 8
    replay = run(app, org_a)
    assert (replay.persisted_count, replay.already_recorded_count) == (0, 4)
    assert len(sources(app, org_a)) == 4
    b_source = sources(app, org_b)[0]
    with db(app) as session, pytest.raises(NotFound):
        source_service._source(session, org_a, b_source.id)


# --- SOURCE-10 ----------------------------------------------------------------------------------------------


def test_cli_dev_only_deterministic_and_audited(app: FastAPI, app_settings: Settings) -> None:
    actor = make_actor(app)

    def cli(environment: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DATABASE_URL": str(app_settings.database_url), "HERMECIOUS_ENV": environment}
        if environment == "production":
            env |= {
                "HERMECIOUS_SESSION_COOKIE_SECURE": "true",
                "HERMECIOUS_ALLOWED_ORIGINS": "https://ops.example.com",
                "HERMECIOUS_CONTACT_HMAC_KEYS": "k1:" + "x" * 32,  # required in production since P4.3
            }
        return subprocess.run(  # noqa: S603  # fixed argv
            [sys.executable, "-m", "app.discovery.cli", "--organization", str(actor.organization_id)],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    refused = cli("production")
    assert refused.returncode == 2 and "development/test only" in refused.stderr
    first, second = cli("test"), cli("test")
    assert first.returncode == second.returncode == 0, first.stderr
    one, two = json.loads(first.stdout), json.loads(second.stdout)
    assert (one["persisted_count"], two["persisted_count"], two["already_recorded_count"]) == (4, 0, 4)
    assert one["label"].startswith("SYNTHETIC") and one["run_id"] != two["run_id"]
    for blob in (first.stdout, second.stdout, first.stderr):
        assert not any(r in blob for r in RAW_RESTRICTED)
    with db(app) as session:
        runs = list(session.scalars(select(ActionAudit).where(ActionAudit.action_type == "discovery.fixture_run")))
    assert len(runs) == 2 and all(r.target_type == "discovery_run" for r in runs)
    assert count(app, Account) == 0
