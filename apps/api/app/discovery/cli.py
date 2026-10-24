"""Discovery run: `python -m app.discovery.cli --organization <uuid> [--provider P] [--keyword K] [--dry-run]`.

Default provider: the offline synthetic fixture (development/test only).
`--provider osm_overpass_schools --confirm-live` makes ONE bounded Overpass
request using the owner-reviewed settings (ADR-013); it refuses unless every
activation setting is present. Prints the run report as JSON; request count
and endpoint go to stderr as evidence. There is no HTTP endpoint that starts a run.
"""

import argparse
import sys
import uuid

from sqlalchemy import select

from app.auth.models import Role, User
from app.auth.service import Actor
from app.core.clock import SystemClock
from app.core.settings import SettingsError, load_settings
from app.discovery import osm
from app.discovery.contracts import SourceAdapter, SourceQuery
from app.discovery.fixture import FixtureLahoreSchoolsAdapter
from app.discovery.registry import FIXTURE_PROVIDER, SourcePolicyError
from app.discovery.runner import run_discovery
from app.persistence.db import make_engine, make_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.discovery.cli", description=__doc__)
    parser.add_argument("--organization", required=True, type=uuid.UUID)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true", help="do not persist provenance")
    parser.add_argument("--provider", choices=[FIXTURE_PROVIDER, osm.PROVIDER], default=FIXTURE_PROVIDER)
    parser.add_argument("--confirm-live", action="store_true", help="required to contact a live provider")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"discovery: {exc}", file=sys.stderr)
        return 2
    live = args.provider == osm.PROVIDER
    if not live and settings.environment not in ("development", "test"):
        print("discovery: refused: the fixture runner is development/test only", file=sys.stderr)
        return 2
    if live and not args.confirm_live:
        print("discovery: refused: live providers need --confirm-live", file=sys.stderr)
        return 2
    adapter: SourceAdapter
    live_adapter: osm.OsmOverpassAdapter | None = None
    if live:
        try:
            adapter = live_adapter = osm.adapter_from_settings(settings)
        except SourcePolicyError as exc:
            print(f"discovery: refused by source policy: {exc.reason}", file=sys.stderr)
            return 1
    else:
        adapter = FixtureLahoreSchoolsAdapter()
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
                adapter=adapter,
                query=SourceQuery(city="Lahore", vertical_slug="schools", keywords=args.keyword),
                persist=not args.dry_run,
            )
        except SourcePolicyError as exc:
            print(f"discovery: refused by source policy: {exc.reason}", file=sys.stderr)
            return 1
    if live_adapter is not None:
        print(f"discovery: endpoint={settings.osm_endpoint} requests={live_adapter.http.requests}", file=sys.stderr)
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
