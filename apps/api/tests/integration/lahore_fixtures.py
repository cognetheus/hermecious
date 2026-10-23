"""Synthetic, Lahore-like school fixtures (P1.2).

Every name is fictional and marked synthetic; every URL uses the reserved
`.example` domain. No real school, person, phone number or address appears.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import FastAPI

from app.accounts import service
from app.accounts.models import Account, SourceRecord
from app.accounts.policy import RIGHTS_POLICY_VERSION
from app.auth.models import Role
from app.auth.service import Actor
from app.core.clock import FixedClock
from tests.integration.auth_helpers import add_organization, db

SCHOOLS_VERTICAL_ID = uuid.UUID("5c4f1d2e-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class SyntheticSchool:
    name: str
    locality: str
    website: str


SCHOOLS = [
    SyntheticSchool("Crescent Valley Grammar School (Synthetic)", "Johar Town", "https://crescent-valley.example"),
    SyntheticSchool("Ravi Bank Public School (Synthetic)", "Shahdara", "http://ravi-bank.example"),
    # Same name as a different campus/locality: must stay two accounts.
    SyntheticSchool("Crescent Valley Grammar School (Synthetic)", "DHA Phase 5", "https://dha.crescent-valley.example"),
]


def actor_for(organization_id: uuid.UUID, role: Role = Role.OWNER) -> Actor:
    return Actor(
        user_id=uuid.uuid4(), organization_id=organization_id, role=role, session_id=uuid.uuid4(), verifier="unused"
    )


def new_org_actor(app: FastAPI, name: str = "Synthetic Ops", role: Role = Role.OWNER) -> Actor:
    return actor_for(add_organization(app, name), role)


def school_account(app: FastAPI, actor: Actor, school: SyntheticSchool = SCHOOLS[0]) -> Account:
    with db(app) as session:
        return service.create_account(
            session,
            actor=actor,
            clock=app.state.clock,
            vertical_id=SCHOOLS_VERTICAL_ID,
            name=school.name,
            city="Lahore",
            locality=school.locality,
        )


def website_source(
    app: FastAPI,
    actor: Actor,
    url: str = "https://crescent-valley.example/admissions",
    storage_class: str = "full_allowed",
    expires_in: timedelta | None = timedelta(days=90),
    external_key: str | None = None,
    provider: str = "first_party_website",
) -> SourceRecord:
    clock: FixedClock = app.state.clock
    with db(app) as session:
        return service.add_source_record(
            session,
            actor=actor,
            clock=clock,
            provider=provider,
            source_url=url,
            observed_at=clock.now() - timedelta(hours=1),
            storage_class=storage_class,
            rights_policy_version=RIGHTS_POLICY_VERSION,
            external_key=external_key,
            expires_at=clock.now() + expires_in if expires_in else None,
        )
