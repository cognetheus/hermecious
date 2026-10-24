"""Seed the default *unpublished* school offer draft: `python -m app.offers.seed`.

Creates `school_admin_starter` under `schools` with every candidate module
`unverified`, nothing approved for sales, no evidence and no prices. Running
it again changes nothing. It never publishes.
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import Vertical
from app.auth.models import Organization, OrganizationStatus, Role, User
from app.auth.service import Actor
from app.core.clock import Clock, SystemClock
from app.core.settings import SettingsError, load_settings
from app.offers import schemas, service
from app.offers.models import Offer
from app.persistence.db import make_engine, make_session_factory

CODE = "school_admin_starter"
CANDIDATE_MODULES = {
    "admissions_intake": "Candidate module: admissions inquiry intake (capability not yet verified)",
    "fee_tracking": "Candidate module: fee collection tracking (capability not yet verified)",
    "student_records": "Candidate module: student records (capability not yet verified)",
    "reporting": "Candidate module: school operations reporting (capability not yet verified)",
}


def starter_content() -> schemas.RevisionContent:
    return schemas.RevisionContent(
        capability_version="unverified-2026-10",
        capability_matrix=[
            schemas.CapabilityClaim(capability_code=code, summary=summary, readiness="unverified")
            for code, summary in CANDIDATE_MODULES.items()
        ],
    )


def seed_school_admin_starter(db: Session, *, owner: User, clock: Clock) -> Offer:
    existing = db.scalar(select(Offer).where(Offer.organization_id == owner.organization_id, Offer.code == CODE))
    if existing is not None:
        return existing
    actor = Actor(
        user_id=owner.id,
        organization_id=owner.organization_id,
        role=Role(owner.role),
        session_id=owner.id,  # not a session; seeding runs outside HTTP
        verifier="",
    )
    vertical = db.scalar(select(Vertical).where(Vertical.slug == "schools"))
    if vertical is None:
        raise RuntimeError("schools vertical missing; run migrations first")
    offer = service.create_offer(
        db, actor=actor, clock=clock, vertical_id=vertical.id, code=CODE, audience="Independent schools in Lahore"
    )
    service.create_revision(
        db, actor=actor, clock=clock, offer_id=offer.id, expected_version=offer.version, content=starter_content()
    )
    db.refresh(offer)
    return offer


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        return 2
    with make_session_factory(make_engine(str(settings.database_url)))() as db:
        owners = list(
            db.scalars(
                select(User)
                .join(Organization, User.organization_id == Organization.id)
                .where(User.role == Role.OWNER, User.active.is_(True), Organization.status == OrganizationStatus.ACTIVE)
            )
        )
        if len(owners) != 1:
            print("seed: refused: expected exactly one active owner (run the bootstrap first)", file=sys.stderr)
            return 1
        offer = seed_school_admin_starter(db, owner=owners[0], clock=SystemClock())
        print(f"seed: offer {offer.code} is {offer.status} (version {offer.version}); nothing was published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
