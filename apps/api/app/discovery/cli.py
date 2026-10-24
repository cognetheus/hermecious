"""Developer/test-only discovery run: `python -m app.discovery.cli --organization <uuid> [--keyword K] [--dry-run]`.

Runs the offline synthetic fixture adapter for Lahore schools with the default
(maximum) budget and prints the DiscoveryFixtureReport as JSON. Refuses to run
outside development/test. There is no HTTP endpoint for discovery in P2.1.
"""

import argparse
import sys
import uuid

from sqlalchemy import select

from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import SystemClock
from app.core.settings import SettingsError, load_settings
from app.discovery.contracts import SourceQuery
from app.discovery.fixture import FixtureLahoreSchoolsAdapter
from app.discovery.registry import SourcePolicyError
from app.discovery.runner import run_discovery
from app.persistence.db import make_engine, make_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.discovery.cli", description=__doc__)
    parser.add_argument("--organization", required=True, type=uuid.UUID)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true", help="do not persist provenance")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"discovery: {exc}", file=sys.stderr)
        return 2
    if settings.environment not in ("development", "test"):
        print("discovery: refused: the fixture runner is development/test only", file=sys.stderr)
        return 2
    factory = make_session_factory(make_engine(str(settings.database_url)))
    with factory() as db:
        owner = db.scalar(
            select(User).where(
                User.organization_id == args.organization, User.role == Role.OWNER, User.active.is_(True)
            )
        )
        if owner is None:
            print("discovery: refused: no active owner in that organization", file=sys.stderr)
            return 1
        actor = Actor(user_id=owner.id, organization_id=owner.organization_id, role=Role.OWNER,
                      session_id=uuid.uuid4(), verifier="")  # fmt: skip
        try:
            report = run_discovery(
                db,
                actor=actor,
                clock=SystemClock(),
                environment=settings.environment,
                adapter=FixtureLahoreSchoolsAdapter(),
                query=SourceQuery(city="Lahore", vertical_slug="schools", keywords=args.keyword),
                persist=not args.dry_run,
            )
        except SourcePolicyError as exc:
            print(f"discovery: refused by source policy: {exc.reason}", file=sys.stderr)
            return 1
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
