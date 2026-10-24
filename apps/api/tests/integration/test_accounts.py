"""P1.2 acceptance: DATA-03..DATA-09 against real Postgres (synthetic data only)."""

import threading
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.accounts import service
from app.accounts.models import Account, AccountAlias, AccountFact, SourceRecord
from app.auth.models import Role
from app.core.clock import FixedClock
from app.core.errors import Conflict, Forbidden, InvalidRequest, NotFound
from app.core.settings import Settings
from tests.integration.auth_helpers import db
from tests.integration.lahore_fixtures import (
    SCHOOLS,
    SCHOOLS_VERTICAL_ID,
    new_org_actor,
    school_account,
    website_source,
)

RIGHTS_MESSAGES = {
    "not on the allowlist",
    "storage class is not permitted",
    "do not permit this",
    "requires a stable external key",
    "do not permit storing a verbatim excerpt",
}


def count(app: FastAPI, model: type[Any]) -> int:
    with db(app) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def fact(app: FastAPI, actor: Any, account_id: uuid.UUID, **overrides: Any) -> AccountFact:
    clock: FixedClock = app.state.clock
    values: dict[str, Any] = {
        "claim_type": "campus_count",
        "typed_value": {"count": 2},
        "confidence_label": "moderate",
        "verification_status": "source_supported",
        "observed_at": clock.now() - timedelta(hours=1),
        **overrides,
    }
    with db(app) as session:
        return service.add_account_fact(session, actor=actor, clock=clock, account_id=account_id, **values)


def raw(app_settings: Settings, sql: str, params: dict[str, Any]) -> None:
    with psycopg.connect(str(app_settings.database_url), autocommit=True) as conn:
        conn.execute(sql, params)


# --- DATA-03 -----------------------------------------------------------------------------------


def test_lahore_school_with_source_supported_fact(app: FastAPI) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor)
    recorded = fact(
        app,
        actor,
        account.id,
        source_record_id=source.id,
        evidence_excerpt="Admissions open at both our campuses.",
    )
    with db(app) as session:
        evidence = service.get_account_with_evidence(session, actor=actor, clock=app.state.clock, account_id=account.id)
    assert evidence.account.city == "Lahore" and evidence.account.status == "discovered"
    assert evidence.account.normalized_name == "crescent valley grammar school synthetic"
    [view] = evidence.facts
    assert view.id == recorded.id and view.value == {"count": 2}
    assert view.verification_status == "source_supported" and not view.is_stale
    assert view.source is not None
    assert view.source.permitted_storage_class == "full_allowed"
    assert view.source.rights_policy_version.startswith("rights-")
    assert view.source.observed_at == app.state.clock.now() - timedelta(hours=1)


# --- DATA-04 -----------------------------------------------------------------------------------


def test_source_supported_without_source_is_rejected_by_service_and_database(
    app: FastAPI, app_settings: Settings
) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    with pytest.raises(InvalidRequest, match="requires a source record"):
        fact(app, actor, account.id)
    with pytest.raises(psycopg.errors.CheckViolation, match="supported_requires_source"):
        raw(
            app_settings,
            "INSERT INTO account_facts (id, organization_id, account_id, claim_type, typed_value_json,"
            " confidence_label, verification_status, observed_at, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, %(acc)s, 'campus_count', '{\"count\": 1}', 'strong',"
            " 'source_supported', now(), now())",
            {"org": actor.organization_id, "acc": account.id},
        )
    assert count(app, AccountFact) == 0


# --- DATA-05 -----------------------------------------------------------------------------------


def test_cross_org_links_fail_in_the_database(app: FastAPI, app_settings: Settings) -> None:
    org_a, org_b = new_org_actor(app, "Org A"), new_org_actor(app, "Org B")
    account_b = school_account(app, org_b)
    source_b = website_source(app, org_b)
    account_a = school_account(app, org_a)
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="fk_account_facts_org_account"):
        raw(
            app_settings,
            "INSERT INTO account_facts (id, organization_id, account_id, claim_type, typed_value_json,"
            " confidence_label, verification_status, observed_at, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, %(acc)s, 'campus_count', '{\"count\": 1}', 'weak',"
            " 'hypothesis', now(), now())",
            {"org": org_a.organization_id, "acc": account_b.id},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="fk_account_facts_org_source"):
        raw(
            app_settings,
            "INSERT INTO account_facts (id, organization_id, account_id, claim_type, typed_value_json,"
            " confidence_label, verification_status, source_record_id, observed_at, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, %(acc)s, 'campus_count', '{\"count\": 1}', 'weak',"
            " 'source_supported', %(src)s, now(), now())",
            {"org": org_a.organization_id, "acc": account_a.id, "src": source_b.id},
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="fk_account_aliases_org_account"):
        raw(
            app_settings,
            "INSERT INTO account_aliases (id, organization_id, account_id, normalized_name, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, %(acc)s, 'x', now())",
            {"org": org_a.organization_id, "acc": account_b.id},
        )
    assert count(app, AccountFact) == 0 and count(app, AccountAlias) == 0


def test_cross_org_service_access_looks_like_not_found(app: FastAPI) -> None:
    org_a, org_b = new_org_actor(app, "Org A"), new_org_actor(app, "Org B")
    account_b = school_account(app, org_b)
    source_b = website_source(app, org_b)
    account_a = school_account(app, org_a)
    clock = app.state.clock
    with db(app) as session, pytest.raises(NotFound):
        service.get_account_with_evidence(session, actor=org_a, clock=clock, account_id=account_b.id)
    with pytest.raises(NotFound):
        fact(app, org_a, account_b.id, verification_status="hypothesis", confidence_label="weak")
    with pytest.raises(NotFound):
        fact(app, org_a, account_a.id, source_record_id=source_b.id)
    with db(app) as session, pytest.raises(NotFound):
        service.add_alias(session, actor=org_a, clock=clock, account_id=account_b.id, name="Stolen alias")
    with db(app) as session, pytest.raises(NotFound):
        service.get_account_with_evidence(session, actor=org_a, clock=clock, account_id=uuid.uuid4())
    assert count(app, AccountFact) == 0


def test_observers_cannot_write_but_can_read(app: FastAPI) -> None:
    owner = new_org_actor(app)
    account = school_account(app, owner)
    observer = owner.__class__(**{**owner.__dict__, "role": Role.OBSERVER})
    with pytest.raises(Forbidden):
        school_account(app, observer)
    with db(app) as session:
        evidence = service.get_account_with_evidence(
            session, actor=observer, clock=app.state.clock, account_id=account.id
        )
    assert evidence.account.id == account.id


# --- DATA-06 -----------------------------------------------------------------------------------


def test_duplicate_external_key_and_alias_are_safe_conflicts(app: FastAPI) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    website_source(app, actor, external_key="seed-list:row-17", provider="owner_seed_list")
    with pytest.raises(Conflict, match="already exists"):
        website_source(app, actor, external_key="seed-list:row-17", provider="owner_seed_list")
    other_org = new_org_actor(app, "Other")
    website_source(app, other_org, external_key="seed-list:row-17", provider="owner_seed_list")  # per-org key
    with db(app) as session:
        service.add_alias(session, actor=actor, clock=app.state.clock, account_id=account.id, name="Crescent Valley")
    with db(app) as session, pytest.raises(Conflict):
        service.add_alias(session, actor=actor, clock=app.state.clock, account_id=account.id, name="CRESCENT  valley!")
    assert count(app, SourceRecord) == 2 and count(app, AccountAlias) == 1


def test_concurrent_duplicate_sources_store_exactly_one(app: FastAPI) -> None:
    actor = new_org_actor(app)
    outcomes: list[str] = []
    barrier = threading.Barrier(6)

    def attempt() -> None:
        barrier.wait()
        try:
            website_source(
                app,
                actor,
                external_key="places:ChIJ-synthetic",
                provider="google_places",
                storage_class="metadata_only",
                url="https://maps.example/place/synthetic",
            )
            outcomes.append("created")
        except Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict"] * 5 + ["created"]
    assert count(app, SourceRecord) == 1


# --- DATA-07 -----------------------------------------------------------------------------------


def test_same_normalized_name_in_two_localities_stays_two_accounts(app: FastAPI) -> None:
    actor = new_org_actor(app)
    first = school_account(app, actor, SCHOOLS[0])
    second = school_account(app, actor, SCHOOLS[2])
    assert first.id != second.id
    assert first.normalized_name == second.normalized_name
    assert (first.locality, second.locality) == ("Johar Town", "DHA Phase 5")
    assert count(app, Account) == 2


# --- DATA-08 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"provider": "random_scraper"}, "not on the allowlist"),
        ({"storage_class": "prohibited"}, "storage class is not permitted"),
        ({"provider": "google_places", "storage_class": "full_allowed", "external_key": "ChIJ1"}, "do not permit this"),
        ({"provider": "google_places", "storage_class": "metadata_only"}, "requires a stable external key"),
        ({"url": "http://169.254.169.254/latest/meta-data"}, "private or internal"),
        ({"url": "https://10.0.0.5/admin"}, "private or internal"),
        ({"url": "https://[::1]/"}, "private or internal"),
        ({"url": "https://localhost/school"}, "private or internal"),
        ({"url": "https://intranet/school"}, "private or internal"),
        ({"url": "https://metadata.google.internal/computeMetadata"}, "private or internal"),
        ({"url": "https://user:pw@crescent-valley.example/"}, "credentials"),
        ({"url": "https://crescent-valley.example/?token=abc123"}, "secret-bearing"),
        ({"url": "https://crescent-valley.example/#section"}, "fragment"),
        ({"url": "ftp://crescent-valley.example/file"}, "scheme"),
        ({"url": "javascript:alert(1)"}, "scheme"),
        ({"url": "http://crescent-valley.example/", "provider": "fixture"}, "scheme"),
        ({"url": "https://crescent-valley.example/‮gnp.exe"}, "malformed"),
        ({"url": "https://crescent-valley.example/" + "a" * 2100}, "malformed"),
    ],
    ids=[
        "unlisted-provider",
        "forbidden-class",
        "places-content",
        "places-no-key",
        "metadata-ip",
        "private-ip",
        "loopback-v6",
        "localhost",
        "single-label",
        "metadata-host",
        "userinfo",
        "secret-query",
        "fragment",
        "ftp",
        "javascript",
        "http-not-allowed",
        "bidi-override",
        "too-long",
    ],
)
def test_forbidden_sources_are_rejected_and_nothing_persists(
    app: FastAPI, overrides: dict[str, Any], message: str
) -> None:
    actor = new_org_actor(app)
    # Rights refusals are 403 (P1.4); malformed or unsafe URLs stay 400.
    expected = Forbidden if message in RIGHTS_MESSAGES else InvalidRequest
    with pytest.raises(expected, match=message):
        website_source(app, actor, **overrides)
    assert count(app, SourceRecord) == 0


def test_payload_requires_full_rights_in_the_database(app: FastAPI, app_settings: Settings) -> None:
    actor = new_org_actor(app)
    with pytest.raises(psycopg.errors.CheckViolation, match="payload_requires_full_rights"):
        raw(
            app_settings,
            "INSERT INTO source_records (id, organization_id, provider, source_url, observed_at,"
            " permitted_storage_class, source_payload_reference, rights_policy_version, created_at)"
            " VALUES (gen_random_uuid(), %(org)s, 'fixture', 'https://a.example', now(), 'metadata_only',"
            " 'blob://copy', 'v1', now())",
            {"org": actor.organization_id},
        )


def test_expired_source_cannot_support_new_facts(app: FastAPI, clock: FixedClock) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor, expires_in=timedelta(days=1))
    clock.advance(timedelta(days=2))
    with pytest.raises(InvalidRequest, match="expired"):
        fact(app, actor, account.id, source_record_id=source.id)
    assert count(app, AccountFact) == 0


@pytest.mark.parametrize(
    ("storage_class", "excerpt", "message"),
    [
        ("metadata_only", "Admissions open.", "do not permit storing a verbatim excerpt"),
        ("derived_only", "Admissions open.", "do not permit storing a verbatim excerpt"),
        ("full_allowed", "x" * 1001, "too long"),
        ("full_allowed", "ok\u0000hidden", "control characters"),
    ],
    ids=["metadata-only", "derived-only", "too-long", "nul-byte"],
)
def test_excerpt_rights_and_bounds(app: FastAPI, storage_class: str, excerpt: str, message: str) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor, storage_class=storage_class)
    expected = Forbidden if message in RIGHTS_MESSAGES else InvalidRequest
    with pytest.raises(expected, match=message):
        fact(app, actor, account.id, source_record_id=source.id, evidence_excerpt=excerpt)
    assert count(app, AccountFact) == 0


# --- DATA-09 -----------------------------------------------------------------------------------


def test_hypothesis_is_distinct_and_unknown_stays_unknown(app: FastAPI) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    fact(
        app,
        actor,
        account.id,
        claim_type="software_in_use",
        typed_value={"status": "unknown"},
        confidence_label="unknown",
        verification_status="hypothesis",
    )
    fact(
        app,
        actor,
        account.id,
        claim_type="ownership_type",
        typed_value={"type": "independent"},
        confidence_label="weak",
        verification_status="hypothesis",
    )
    with db(app) as session:
        evidence = service.get_account_with_evidence(session, actor=actor, clock=app.state.clock, account_id=account.id)
    statuses = {f.claim_type: (f.verification_status, f.confidence_label, f.source) for f in evidence.facts}
    assert statuses == {
        "software_in_use": ("hypothesis", "unknown", None),
        "ownership_type": ("hypothesis", "weak", None),
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"typed_value": {"count": 0}}, "invalid for its type"),
        ({"typed_value": {"count": "2"}}, "invalid for its type"),
        ({"typed_value": {"count": 2, "extra": True}}, "invalid for its type"),
        ({"claim_type": "software_in_use", "typed_value": {"status": "none"}}, "invalid for its type"),
        ({"claim_type": "website_presence", "typed_value": {"status": "absent"}}, "invalid for its type"),
        ({"claim_type": "likelihood_to_buy", "typed_value": {"percent": 80}}, "not on the allowlist"),
        ({"claim_type": "principal_mobile", "typed_value": {"phone": "+923001234567"}}, "not on the allowlist"),
        (
            {"claim_type": "decision_authority", "typed_value": {"holder": "unknown"}, "confidence_label": "weak"},
            "unknown value can only be a hypothesis",
        ),
        ({"verification_status": "hypothesis", "confidence_label": "strong"}, "cannot have strong"),
        ({"verification_status": "disputed"}, "must be source_supported or hypothesis"),
        ({"observed_at": datetime(2026, 10, 23, 7, 0)}, "timezone offset"),  # noqa: DTZ001
        ({"observed_at": datetime(2026, 10, 30, tzinfo=UTC)}, "in the future"),
    ],
    ids=[
        "zero-campuses",
        "string-count",
        "extra-field",
        "negative-software",
        "negative-website",
        "buy-likelihood",
        "personal-phone",
        "unknown-as-finding",
        "strong-hypothesis",
        "disputed-on-create",
        "naive-timestamp",
        "future-timestamp",
    ],
)
def test_invalid_or_overclaiming_facts_are_rejected(app: FastAPI, overrides: dict[str, Any], message: str) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor)
    with pytest.raises(InvalidRequest, match=message):
        fact(app, actor, account.id, source_record_id=source.id, **overrides)
    assert count(app, AccountFact) == 0


def test_offset_timestamps_are_normalized_to_utc(app: FastAPI) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor)
    karachi = timezone(timedelta(hours=5))
    observed = datetime(2026, 10, 23, 10, 0, tzinfo=karachi)
    recorded = fact(app, actor, account.id, source_record_id=source.id, observed_at=observed)
    with db(app) as session:
        stored = session.get(AccountFact, recorded.id)
        assert stored is not None
        assert stored.observed_at == datetime(2026, 10, 23, 5, 0, tzinfo=UTC)


def test_fact_becomes_stale_when_its_source_expires(app: FastAPI, clock: FixedClock) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    source = website_source(app, actor, expires_in=timedelta(days=30))
    fact(app, actor, account.id, source_record_id=source.id)
    clock.advance(timedelta(days=31))
    with db(app) as session:
        evidence = service.get_account_with_evidence(session, actor=actor, clock=clock, account_id=account.id)
    [view] = evidence.facts
    assert view.is_stale and view.verification_status == "source_supported"


# --- Failure simulations -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["   ", "School‮loohcS", "Null\u0000Byte School", "x" * 251],
    ids=["blank", "bidi-override", "nul", "too-long"],
)
def test_malicious_account_names_are_rejected(app: FastAPI, name: str) -> None:
    actor = new_org_actor(app)
    with db(app) as session, pytest.raises(InvalidRequest):
        service.create_account(
            session, actor=actor, clock=app.state.clock, vertical_id=SCHOOLS_VERTICAL_ID, name=name, city="Lahore"
        )
    assert count(app, Account) == 0


def test_unicode_names_are_normalized_not_rejected(app: FastAPI) -> None:
    actor = new_org_actor(app)
    with db(app) as session:
        account = service.create_account(
            session,
            actor=actor,
            clock=app.state.clock,
            vertical_id=SCHOOLS_VERTICAL_ID,
            name="  دی  لاہور   گرامر اسکول (Synthetic)  ",
            city="Lahore",
        )
    assert account.canonical_name == "دی لاہور گرامر اسکول (Synthetic)"
    assert account.normalized_name == "دی لاہور گرامر اسکول synthetic"


def test_unknown_or_inactive_vertical_is_not_found(app: FastAPI) -> None:
    actor = new_org_actor(app)
    with db(app) as session, pytest.raises(NotFound):
        service.create_account(
            session, actor=actor, clock=app.state.clock, vertical_id=uuid.uuid4(), name="X School", city="Lahore"
        )


def test_failed_fact_insert_leaves_session_usable_and_nothing_partial(app: FastAPI, app_settings: Settings) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    with db(app) as session:
        session.begin_nested()
        session.add(
            AccountFact(
                organization_id=actor.organization_id,
                account_id=account.id,
                claim_type="campus_count",
                typed_value_json={"count": 1},
                confidence_label="unknown",
                verification_status="source_supported",
                observed_at=app.state.clock.now(),
                created_at=app.state.clock.now(),
            )
        )
        with pytest.raises(Exception, match="supported_requires_source|supported_not_unknown"):
            session.flush()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(AccountFact)) == 0
    assert count(app, AccountFact) == 0


def test_optimistic_version_rejects_a_stale_writer(app: FastAPI) -> None:
    actor = new_org_actor(app)
    account = school_account(app, actor)
    with db(app) as first, db(app) as second:
        a = first.get(Account, account.id)
        b = second.get(Account, account.id)
        assert a is not None and b is not None and a.version == b.version == 1
        a.status = "researching"
        first.commit()
        b.status = "excluded"
        with pytest.raises(Exception, match="StaleData|expected to update"):
            second.commit()
    with db(app) as session:
        current = session.get(Account, account.id)
        assert current is not None and (current.status, current.version) == ("researching", 2)
