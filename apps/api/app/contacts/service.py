"""Contacts, permission evidence and suppressions (P4.3, ADR-022).

- Addresses are kept only as keyed digests plus a masked hint; proof references only as keyed digests.
- `record_permission` always creates **pending** evidence. Only an owner who did not record it may verify it, and
  every evidence check is repeated at verification. Nothing is granted automatically or by a model.
- Revocation and suppression are independent. A suppression is org-wide and dominates every campaign.
- Every command is idempotent (same key + same request = same outcome; same key + different request = 409).
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account
from app.auth.dependencies import Capability
from app.auth.models import User
from app.auth.service import Actor
from app.contacts import addresses
from app.contacts.models import Contact, ContactCommand, ContactPermission, SuppressionEntry
from app.core.clock import Clock
from app.core.errors import Conflict, DependencyUnavailable, Forbidden, NotFound, Unprocessable
from app.core.settings import Settings
from app.eligibility import policy

CLOCK_SKEW = timedelta(minutes=5)


def keyring(settings: Settings) -> addresses.Keyring:
    """Fail closed: without configured keys no contact can be stored or matched (there is no built-in key)."""
    if settings.contact_hmac_secrets is None:
        raise DependencyUnavailable("contact keys are not configured (HERMECIOUS_CONTACT_HMAC_SECRETS)")
    return addresses.parse_keyring(settings.contact_hmac_secrets.get_secret_value())


# --- idempotency --------------------------------------------------------------------------------------------


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _replay(db: Session, org: uuid.UUID, key: str, digest: str) -> dict[str, Any] | None:
    prior = db.scalar(
        select(ContactCommand).where(ContactCommand.organization_id == org, ContactCommand.idempotency_key == key)
    )
    if prior is None:
        return None
    if prior.request_digest != digest:
        raise Conflict("idempotency_key was already used with a different request")
    return prior.outcome_json


def _command(
    db: Session, actor: Actor, clock: Clock, key: str, digest: str, run: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """Run `run` once per (org, key). Returns (outcome, created)."""
    org = actor.organization_id
    if (prior := _replay(db, org, key, digest)) is not None:
        return prior, False
    outcome = run()
    db.add(
        ContactCommand(
            organization_id=org,
            idempotency_key=key,
            request_digest=digest,
            outcome_json=outcome,
            created_at=clock.now(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if (prior := _replay(db, org, key, digest)) is not None:
            return prior, False
        raise Conflict("this record changed concurrently; reload and try again") from None
    return outcome, True


# --- reads ----------------------------------------------------------------------------------------------------


def get(db: Session, org: uuid.UUID, contact_id: uuid.UUID) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.organization_id == org, Contact.id == contact_id))
    if contact is None:
        raise NotFound()
    return contact


def suppression(db: Session, contact: Contact) -> SuppressionEntry | None:
    return db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.organization_id == contact.organization_id,
            SuppressionEntry.channel == contact.channel,
            SuppressionEntry.key_id == contact.key_id,
            SuppressionEntry.address_digest == contact.address_digest,
        )
    )


def suppression_revision(db: Session, org: uuid.UUID) -> int:
    """Suppressions are append-only, so their count is a monotonic revision of the org's suppression list."""
    return int(
        db.scalar(select(func.count()).select_from(SuppressionEntry).where(SuppressionEntry.organization_id == org))
        or 0
    )


def permissions(db: Session, contact: Contact) -> list[ContactPermission]:
    return list(
        db.scalars(
            select(ContactPermission)
            .where(
                ContactPermission.organization_id == contact.organization_id,
                ContactPermission.contact_id == contact.id,
            )
            .order_by(ContactPermission.recorded_at.desc(), ContactPermission.id)
        )
    )


def _people(db: Session, org: uuid.UUID, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = db.execute(
        select(User.id, User.display_name, User.email_canonical).where(User.organization_id == org, User.id.in_(wanted))
    )
    return {uid: name or email for uid, name, email in rows}


def _permission_view(p: ContactPermission, people: dict[uuid.UUID, str], full: bool) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": str(p.id),
        "purpose": p.purpose,
        "channel": p.channel,
        "status": p.status,
        "version": p.version,
        "expires_at": p.expires_at.isoformat(),
    }
    if not full:
        return view
    return view | {
        "business_name": p.business_name,
        "basis": p.basis,
        "capture_method": p.capture_method,
        "consent_wording_version": p.consent_wording_version,
        "proof": {"kind": p.proof_kind, "reference": "kept only as a keyed digest", "key_id": p.proof_key_id},
        "captured_at": p.captured_at.isoformat(),
        "recorded_at": p.recorded_at.isoformat(),
        "recorded_by": people.get(p.recorded_by),
        "reviewed_by": people.get(p.reviewed_by) if p.reviewed_by else None,
        "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "review_reason": p.review_reason,
        "effective_at": p.effective_at.isoformat() if p.effective_at else None,
        "revoked_by": people.get(p.revoked_by) if p.revoked_by else None,
        "revoked_at": p.revoked_at.isoformat() if p.revoked_at else None,
        "revoke_reason": p.revoke_reason,
        "supersedes_id": str(p.supersedes_id) if p.supersedes_id else None,
    }


def view(db: Session, contact: Contact, *, full: bool) -> dict[str, Any]:
    """Masked view. `full` (owners/operators) adds evidence metadata; observers see status only."""
    rows = permissions(db, contact)
    people = _people(
        db,
        contact.organization_id,
        {p.recorded_by for p in rows} | {p.reviewed_by for p in rows} | {p.revoked_by for p in rows},
    )
    entry = suppression(db, contact)
    return {
        "id": str(contact.id),
        "account_id": str(contact.account_id),
        "channel": contact.channel,
        "role": contact.role,
        "address": contact.address_hint,
        "suppressed": entry is not None,
        "suppression": (
            {"reason": entry.reason, "created_at": entry.created_at.isoformat()} if entry is not None else None
        ),
        "permissions": [_permission_view(p, people, full) for p in rows],
    }


def list_for_account(db: Session, org: uuid.UUID, account_id: uuid.UUID) -> list[Contact]:
    if db.scalar(select(Account.id).where(Account.organization_id == org, Account.id == account_id)) is None:
        raise NotFound()
    return list(
        db.scalars(
            select(Contact)
            .where(Contact.organization_id == org, Contact.account_id == account_id)
            .order_by(Contact.created_at, Contact.id)
        )
    )


# --- contacts ------------------------------------------------------------------------------------------------


def create_contact(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    keys: addresses.Keyring,
    account_id: uuid.UUID,
    address: str,
    role: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    try:
        e164 = addresses.canonical(address)
    except addresses.AddressError:
        raise Unprocessable("INVALID_ADDRESS: not a valid international phone number") from None
    key_id, key = keys.current
    every = addresses.digests(keys, e164)
    request = _digest("contact", str(account_id), every[key_id], role)

    def run() -> dict[str, Any]:
        if db.scalar(select(Account.id).where(Account.organization_id == org, Account.id == account_id)) is None:
            raise NotFound()
        clash = db.scalar(
            select(Contact.id).where(
                Contact.organization_id == org,
                Contact.channel == "whatsapp",
                func.concat(Contact.key_id, ":", Contact.address_digest).in_([f"{k}:{d}" for k, d in every.items()]),
            )
        )
        if clash is not None:
            raise Conflict("this number is already a contact in your organization")
        now = clock.now()
        contact = Contact(
            organization_id=org,
            account_id=account_id,
            channel="whatsapp",
            role=role,
            key_id=key_id,
            address_digest=every[key_id],
            address_hint=addresses.mask(e164),
            created_by=actor.user_id,
            created_at=now,
        )
        db.add(contact)
        db.flush()
        management._audit(
            db,
            actor,
            clock,
            "contact.created",
            contact.id,
            {"account_id": str(account_id), "role": role, "key_id": key_id, "address": contact.address_hint},
            target_type="contact",
        )
        return {"contact_id": str(contact.id)}

    return _command(db, actor, clock, idempotency_key, request, run)


# --- permission evidence -------------------------------------------------------------------------------------


def evidence_problems(
    *, purpose: str, business_name: str, consent_wording_version: str, captured_at: datetime, now: datetime
) -> list[str]:
    """Why evidence cannot stand (empty = acceptable). Checked at capture and again at verification."""
    problems = []
    if purpose not in policy.CONSENT_WORDING:
        problems.append("purpose_not_recordable")
    if business_name != policy.BUSINESS_NAME:
        problems.append("wrong_business")
    if consent_wording_version != policy.CONSENT_WORDING.get(purpose):
        problems.append("unknown_consent_wording")
    if captured_at > now + CLOCK_SKEW:
        problems.append("future_dated")
    elif now - captured_at > policy.PROOF_MAX_AGE:
        problems.append("proof_stale")
    return problems


def record_permission(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    keys: addresses.Keyring,
    contact_id: uuid.UUID,
    purpose: str,
    business_name: str,
    capture_method: str,
    consent_wording_version: str,
    proof_kind: str,
    proof_reference: str,
    captured_at: datetime,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Always **pending**. Supersedes any open evidence for the same purpose (an edit invalidates the old one)."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    key_id, key = keys.current
    proof = addresses.proof_digest(key, proof_reference)
    request = _digest(
        "permission",
        str(contact_id),
        purpose,
        business_name,
        capture_method,
        consent_wording_version,
        proof_kind,
        proof,
        captured_at.isoformat(),
    )

    def run() -> dict[str, Any]:
        contact = get(db, org, contact_id)
        now = clock.now()
        problems = evidence_problems(
            purpose=purpose,
            business_name=business_name,
            consent_wording_version=consent_wording_version,
            captured_at=captured_at,
            now=now,
        )
        if problems:
            raise Unprocessable("EVIDENCE_REJECTED: " + ", ".join(problems))
        prior = db.scalar(
            select(ContactPermission)
            .where(
                ContactPermission.organization_id == org,
                ContactPermission.contact_id == contact.id,
                ContactPermission.purpose == purpose,
                ContactPermission.status.in_(("pending", "verified")),
            )
            .with_for_update()
        )
        if prior is not None:
            db.execute(
                update(ContactPermission)
                .where(ContactPermission.id == prior.id, ContactPermission.version == prior.version)
                .values(status="superseded", version=prior.version + 1)
            )
        permission = ContactPermission(
            organization_id=org,
            contact_id=contact.id,
            channel="whatsapp",
            purpose=purpose,
            business_name=business_name,
            basis="explicit_opt_in",
            capture_method=capture_method,
            consent_wording_version=consent_wording_version,
            proof_kind=proof_kind,
            proof_key_id=key_id,
            proof_digest=proof,
            captured_at=captured_at,
            recorded_at=now,
            expires_at=captured_at + policy.PROOF_MAX_AGE,
            status="pending",
            recorded_by=actor.user_id,
            supersedes_id=prior.id if prior is not None else None,
            version=1,
        )
        db.add(permission)
        db.flush()
        management._audit(
            db,
            actor,
            clock,
            "contact_permission.recorded",
            contact.id,
            {
                "permission_id": str(permission.id),
                "purpose": purpose,
                "capture_method": capture_method,
                "status": "pending",
                "supersedes_id": str(prior.id) if prior is not None else None,
                "input_digest": request,
            },
            target_type="contact",
        )
        return {"contact_id": str(contact.id), "permission_id": str(permission.id), "status": "pending"}

    return _command(db, actor, clock, idempotency_key, request, run)


def _locked(db: Session, org: uuid.UUID, contact_id: uuid.UUID, permission_id: uuid.UUID) -> ContactPermission:
    permission = db.scalar(
        select(ContactPermission)
        .where(
            ContactPermission.organization_id == org,
            ContactPermission.contact_id == contact_id,
            ContactPermission.id == permission_id,
        )
        .with_for_update()
    )
    if permission is None:
        raise NotFound()
    return permission


def review_permission(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    contact_id: uuid.UUID,
    permission_id: uuid.UUID,
    decision: str,
    reason: str,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Owner-only. `verified` re-checks the evidence now; the reviewer must not be the person who recorded it."""
    account_service._require(actor, Capability.ADMINISTER)
    org = actor.organization_id
    reason = " ".join(reason.split())
    request = _digest("review", str(contact_id), str(permission_id), decision, reason, expected_version)

    def run() -> dict[str, Any]:
        permission = _locked(db, org, contact_id, permission_id)
        if permission.version != expected_version:
            raise Conflict("this evidence changed since you loaded it; reload")
        if permission.status != "pending":
            raise Conflict(f"only pending evidence can be reviewed (this is {permission.status})")
        now = clock.now()
        if decision == "verified":
            if permission.recorded_by == actor.user_id:
                raise Forbidden("evidence must be verified by someone other than the person who recorded it")
            problems = evidence_problems(
                purpose=permission.purpose,
                business_name=permission.business_name,
                consent_wording_version=permission.consent_wording_version,
                captured_at=permission.captured_at,
                now=now,
            )
            if permission.expires_at <= now:
                problems.append("expired")
            if suppression(db, get(db, org, contact_id)) is not None:
                problems.append("suppressed")
            if problems:
                raise Unprocessable("EVIDENCE_REJECTED: " + ", ".join(problems))
        values: dict[str, Any] = {
            "status": decision,
            "reviewed_by": actor.user_id,
            "reviewed_at": now,
            "review_reason": reason,
            "version": permission.version + 1,
        }
        if decision == "verified":
            values["effective_at"] = now
        db.execute(update(ContactPermission).where(ContactPermission.id == permission.id).values(**values))
        management._audit(
            db,
            actor,
            clock,
            f"contact_permission.{decision}",
            permission.contact_id,
            {"permission_id": str(permission.id), "reason": reason, "version": permission.version + 1},
            target_type="contact",
        )
        return {"permission_id": str(permission.id), "status": decision, "version": permission.version + 1}

    return _command(db, actor, clock, idempotency_key, request, run)


def revoke_permission(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    contact_id: uuid.UUID,
    permission_id: uuid.UUID,
    reason: str,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    reason = " ".join(reason.split())
    request = _digest("revoke", str(contact_id), str(permission_id), reason, expected_version)

    def run() -> dict[str, Any]:
        permission = _locked(db, org, contact_id, permission_id)
        if permission.version != expected_version:
            raise Conflict("this evidence changed since you loaded it; reload")
        if permission.status not in ("pending", "verified"):
            raise Conflict(f"this evidence is already {permission.status}")
        now = clock.now()
        db.execute(
            update(ContactPermission)
            .where(ContactPermission.id == permission.id)
            .values(
                status="revoked",
                revoked_by=actor.user_id,
                revoked_at=now,
                revoke_reason=reason,
                version=permission.version + 1,
            )
        )
        management._audit(
            db,
            actor,
            clock,
            "contact_permission.revoked",
            permission.contact_id,
            {"permission_id": str(permission.id), "reason": reason, "version": permission.version + 1},
            target_type="contact",
        )
        return {"permission_id": str(permission.id), "status": "revoked", "version": permission.version + 1}

    return _command(db, actor, clock, idempotency_key, request, run)


# --- suppression -------------------------------------------------------------------------------------------


def suppress(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    contact_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Org-wide and permanent in P4.3. A second suppression of the same number converges on the first."""
    account_service._require(actor, Capability.MUTATE)
    org = actor.organization_id
    request = _digest("suppress", str(contact_id), reason)

    def run() -> dict[str, Any]:
        contact = get(db, org, contact_id)
        now = clock.now()
        created = db.scalar(
            insert(SuppressionEntry)
            .values(
                id=uuid.uuid4(),
                organization_id=org,
                channel=contact.channel,
                key_id=contact.key_id,
                address_digest=contact.address_digest,
                address_hint=contact.address_hint,
                reason=reason,
                contact_id=contact.id,
                created_by=actor.user_id,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_suppression_address")
            .returning(SuppressionEntry.id)
        )
        if created is not None:
            management._audit(
                db,
                actor,
                clock,
                "contact.suppressed",
                contact.id,
                {"reason": reason, "key_id": contact.key_id},
                target_type="contact",
            )
        return {"contact_id": str(contact.id), "suppressed": True, "already_suppressed": created is None}

    return _command(db, actor, clock, idempotency_key, request, run)
