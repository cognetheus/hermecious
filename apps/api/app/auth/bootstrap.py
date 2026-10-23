"""Owner bootstrap: `python -m app.auth.bootstrap --organization NAME --email EMAIL [--display-name NAME]`.

Creates the single initial organization and its owner, once. The password is
read interactively from a TTY (twice); there is no password argument, no
default credential, and nothing secret or personal is printed or logged.
"""

import argparse
import getpass
import sys
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import passwords
from app.auth.models import Organization, OrganizationStatus, Role, User
from app.core.clock import Clock, SystemClock
from app.core.settings import SettingsError, load_settings
from app.persistence.db import make_engine, make_session_factory

# Serializes concurrent bootstrap attempts; any constant unique to this operation.
BOOTSTRAP_LOCK_KEY = 0x4845524D_424F4F54  # "HERM" "BOOT"


class BootstrapRefused(RuntimeError):
    pass


def bootstrap_owner(
    db: Session,
    *,
    organization_name: str,
    email: str,
    password: str,
    display_name: str | None,
    clock: Clock,
) -> User:
    organization_name = organization_name.strip()
    email = passwords.canonical_email(email)
    if not 1 <= len(organization_name) <= 200:
        raise BootstrapRefused("organization name must be 1-200 characters")
    if "@" not in email or len(email) > 320:
        raise BootstrapRefused("email address is not valid")
    try:
        passwords.check_policy(password, email)
    except passwords.PasswordPolicyError as exc:
        raise BootstrapRefused(str(exc)) from None

    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BOOTSTRAP_LOCK_KEY})
    if db.scalar(select(func.count()).select_from(Organization)):
        db.rollback()
        raise BootstrapRefused("already bootstrapped: an organization exists; refusing to create another owner")

    now: datetime = clock.now()
    organization = Organization(name=organization_name, status=OrganizationStatus.ACTIVE, created_at=now)
    db.add(organization)
    db.flush()
    owner = User(
        organization_id=organization.id,
        email_canonical=email,
        display_name=(display_name or "").strip() or None,
        password_hash=passwords.hash_password(password),
        role=Role.OWNER,
        active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(owner)
    db.commit()
    return owner


def _read_password() -> str:
    first = getpass.getpass("Owner password: ")
    if first != getpass.getpass("Repeat password: "):
        raise BootstrapRefused("passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.bootstrap", description=__doc__)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name")
    args = parser.parse_args(argv)

    if not sys.stdin.isatty():
        print("bootstrap: refusing to run without an interactive terminal (password is prompted)", file=sys.stderr)
        return 2
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"bootstrap: {exc}", file=sys.stderr)
        return 2
    try:
        password = _read_password()
        engine = make_engine(str(settings.database_url))
        with make_session_factory(engine)() as db:
            bootstrap_owner(
                db,
                organization_name=args.organization,
                email=args.email,
                password=password,
                display_name=args.display_name,
                clock=SystemClock(),
            )
    except BootstrapRefused as exc:
        print(f"bootstrap: refused: {exc}", file=sys.stderr)
        return 1
    print("bootstrap: organization and owner created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
