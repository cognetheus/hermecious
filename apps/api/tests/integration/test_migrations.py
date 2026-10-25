"""Migration harness against real, per-test scratch databases on the test server."""

from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy.engine import URL

from app.core.settings import Settings
from tests.integration.db import alembic, plain, scratch_database

HEAD = "0019"


@pytest.fixture
def scratch_database_url(settings: Settings) -> Iterator[URL]:
    with scratch_database(str(settings.database_url)) as url:
        yield url


def current_revision(database_url: URL) -> list[str]:
    with psycopg.connect(plain(database_url)) as conn:
        exists = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()
        if not exists or not exists[0]:
            return []
        return [row[0] for row in conn.execute("SELECT version_num FROM alembic_version")]


def test_upgrade_head_is_repeatable(scratch_database_url: URL) -> None:
    first = alembic("upgrade", "head", database_url=scratch_database_url)
    assert first.returncode == 0, first.stderr
    assert current_revision(scratch_database_url) == [HEAD]

    second = alembic("upgrade", "head", database_url=scratch_database_url)
    assert second.returncode == 0, second.stderr
    assert current_revision(scratch_database_url) == [HEAD]


def test_downgrade_to_base_and_back(scratch_database_url: URL) -> None:
    up = alembic("upgrade", "head", database_url=scratch_database_url)
    assert up.returncode == 0, up.stderr
    down = alembic("downgrade", "base", database_url=scratch_database_url)
    assert down.returncode == 0, down.stderr
    assert current_revision(scratch_database_url) == []
    again = alembic("upgrade", "head", database_url=scratch_database_url)
    assert again.returncode == 0, again.stderr
    assert current_revision(scratch_database_url) == [HEAD]


@pytest.mark.parametrize(
    "bad_url",
    ["", "not-a-url", "mysql://user:pw-secret-value@db/app_test"],
    ids=["empty", "malformed", "wrong-scheme"],
)
def test_invalid_database_url_refuses_to_migrate(bad_url: str) -> None:
    result = alembic("upgrade", "head", database_url=bad_url)
    assert result.returncode != 0
    assert "refusing to run: missing or invalid settings: DATABASE_URL" in result.stderr
    assert "pw-secret-value" not in result.stderr + result.stdout


def test_unreachable_database_fails_without_fallback() -> None:
    # Valid URL, nothing listening: the migration must fail, not pick another database.
    result = alembic("upgrade", "head", database_url="postgresql://user:pw@127.0.0.1:1/nowhere_test")
    assert result.returncode != 0
    assert "OperationalError" in result.stderr


def test_models_match_migrations(scratch_database_url: URL) -> None:
    """Drift guard: the ORM metadata and the migrated schema describe the same tables."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.persistence.base import Base, sqlalchemy_url
    from app.persistence.registry import register_models

    assert alembic("upgrade", "head", database_url=scratch_database_url).returncode == 0
    register_models()
    engine = create_engine(sqlalchemy_url(plain(scratch_database_url)))
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert diff == []


CORE_TABLES = {"verticals", "areas", "accounts", "source_records", "account_aliases", "account_facts"}
CORE_CONSTRAINTS = {
    "fk_account_facts_org_account",
    "fk_account_facts_org_source",
    "fk_account_aliases_org_account",
    "fk_account_aliases_org_source",
    "ck_account_facts_supported_requires_source",
    "ck_source_records_payload_requires_full_rights",
    "uq_accounts_organization_id_id",
    "uq_source_records_organization_id_id",
    "uq_account_aliases_organization_id_account_id_normalized_name",
}
CORE_INDEXES = {
    "uq_areas_org_city_district",
    "uq_source_records_org_provider_external_key",
    "ix_accounts_org_vertical_city_status",
    "ix_account_facts_org_account_claim_observed",
}


def catalog(database_url: URL) -> tuple[set[str], set[str], set[str], list[str]]:
    with psycopg.connect(plain(database_url)) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        constraints = {r[0] for r in conn.execute("SELECT conname FROM pg_constraint")}
        indexes = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")}
        verticals = [r[0] for r in conn.execute("SELECT slug FROM verticals")] if "verticals" in tables else []
    return tables, constraints, indexes, verticals


def test_core_domain_objects_exist_and_reupgrade_is_a_noop(scratch_database_url: URL) -> None:
    """DATA-01."""
    assert alembic("upgrade", "head", database_url=scratch_database_url).returncode == 0
    first = catalog(scratch_database_url)
    tables, constraints, indexes, verticals = first
    assert tables >= CORE_TABLES
    assert constraints >= CORE_CONSTRAINTS
    assert indexes >= CORE_INDEXES
    assert verticals == ["schools"]
    again = alembic("upgrade", "head", database_url=scratch_database_url)
    assert again.returncode == 0 and "Running upgrade" not in again.stderr
    assert catalog(scratch_database_url) == first


def test_downgrade_of_populated_core_domain_preserves_identity(scratch_database_url: URL) -> None:
    """DATA-02: P1.2 tables go; P1.1 users and sessions stay; re-upgrade restores an empty P1.2 schema."""
    assert alembic("upgrade", "head", database_url=scratch_database_url).returncode == 0
    with psycopg.connect(plain(scratch_database_url), autocommit=True) as conn:
        org, user, session = conn.execute(
            "WITH o AS (INSERT INTO organizations (id, name, status, created_at)"
            "           VALUES (gen_random_uuid(), 'Synthetic Org', 'active', now()) RETURNING id),"
            " u AS (INSERT INTO users (id, organization_id, email_canonical, password_hash, role,"
            "       created_at, updated_at)"
            "       SELECT gen_random_uuid(), o.id, 'owner@synthetic.example', 'x', 'owner', now(), now() FROM o"
            "       RETURNING id, organization_id),"
            " s AS (INSERT INTO auth_sessions (id, user_id, verifier_hash, issued_at, idle_expires_at,"
            "       absolute_expires_at) SELECT gen_random_uuid(), u.id, repeat('a', 64), now(),"
            "       now() + interval '1 hour', now() + interval '2 hours' FROM u RETURNING id)"
            " SELECT (SELECT id FROM o), (SELECT id FROM u), (SELECT id FROM s)"
        ).fetchone() or (None, None, None)
        conn.execute(
            "INSERT INTO accounts (id, organization_id, vertical_id, canonical_name, normalized_name, city, status,"
            " discovered_at, updated_at) SELECT gen_random_uuid(), %s, id, 'Synthetic School', 'synthetic school',"
            " 'Lahore', 'discovered', now(), now() FROM verticals WHERE slug = 'schools'",
            (org,),
        )
    down = alembic("downgrade", "0002", database_url=scratch_database_url)
    assert down.returncode == 0, down.stderr
    assert current_revision(scratch_database_url) == ["0002"]
    tables, *_ = catalog(scratch_database_url)
    assert not (CORE_TABLES & tables)
    with psycopg.connect(plain(scratch_database_url)) as conn:
        assert conn.execute("SELECT count(*) FROM users WHERE id = %s", (user,)).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM auth_sessions WHERE id = %s", (session,)).fetchone() == (1,)
    up = alembic("upgrade", "head", database_url=scratch_database_url)
    assert up.returncode == 0, up.stderr
    with psycopg.connect(plain(scratch_database_url)) as conn:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (1,)
