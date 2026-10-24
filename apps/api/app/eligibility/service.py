"""`ChannelEligibilityService` (P4.3, ADR-022): gathers current facts from the database and applies the policy.

Each call reads the database afresh (no cached allow, no token). The decision is recorded as a compact audit
row (actor, reasons, input digest, policy version; never an address or proof) and returned with
`live_send_authorized: false`. Nothing is queued, scheduled or sent.

Trust boundary:
- template approval comes only from signed synthetic fixtures (non-production, synthetic accounts only);
- inbound service context comes only from signed synthetic fixtures; a client never supplies a time;
- campaign, gate, offer, evidence and membership state come from the same checks Draft Studio uses;
- usage counters are zero: no send ledger exists in P4.3 (P4.5 simulations will feed them).
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import management
from app.accounts import service as account_service
from app.accounts.models import Account
from app.auth.dependencies import Capability
from app.auth.models import User
from app.auth.service import Actor
from app.campaigns import service as campaign_service
from app.contacts import addresses
from app.contacts import service as contacts
from app.core.clock import Clock
from app.core.errors import NotFound
from app.core.settings import Settings
from app.drafts import service as drafts
from app.eligibility import fixtures, policy
from app.evaluation import service as evaluation

NOTICE = "Simulation eligibility only — sending disabled"
FIXTURE_BLOCKER = "fixture_requires_synthetic_account_outside_production"

EXPLANATIONS = {
    "kill_switch_engaged": "The global outreach kill switch is on.",
    "campaign_paused": "The campaign is paused.",
    "campaign_cancelled": "The campaign is cancelled.",
    "suppressed": "This number opted out or was suppressed; that overrides every campaign.",
    "no_opt_in_permission": "No opt-in is on record. A public phone number is not permission.",
    "permission_unverified": "Opt-in evidence is recorded but an owner has not verified it.",
    "permission_revoked": "The opt-in was revoked.",
    "purpose_not_covered": "The verified opt-in does not cover this purpose.",
    "wrong_business": "The opt-in names a different business.",
    "permission_expired": "The opt-in has expired.",
    "proof_future_dated": "The opt-in proof is dated in the future.",
    "proof_stale": "The opt-in proof is older than a year.",
    "consent_wording_outdated": "The opt-in used consent wording that is not current.",
    "template_missing": "Business-initiated messages need a provider-approved template.",
    "template_unverified": "The template is not provider-approved (only signed synthetic fixtures count before P5).",
    "template_rejected": "The template was rejected by the provider.",
    "template_wrong_category": "The template category does not match the purpose.",
    FIXTURE_BLOCKER: "Synthetic fixtures apply only to synthetic accounts outside production.",
    "no_inbound_context": "A service reply needs an official inbound message.",
    "inbound_context_mismatch": "The inbound message came from a different number.",
    "inbound_context_invalid": "The inbound message time is invalid.",
    "service_window_closed": "The 24-hour service window after the last inbound message has closed.",
    "campaign_required": "Business-initiated messages need a campaign.",
    "not_approved_for_drafting": "The account is not approved in this campaign.",
    "excluded": "The account is excluded from this campaign.",
    "evidence_quality_gate_closed": "The evidence-quality gate is closed.",
    "fixture_campaigns_are_test_only_in_production": "Fixture campaigns are test-only.",
    "rules_changed": "The campaign rules changed since approval.",
    "offer_changed": "The campaign offer changed since approval.",
    "offer_not_published": "The campaign offer is no longer published.",
    "assessment_superseded": "The account was reassessed since approval.",
    "evidence_changed": "The account's evidence or source rights changed since approval.",
    "no_active_human_owner": "No active person owns this conversation.",
    "outside_business_hours": "Outside business hours (Mon–Sat 09:00–18:00, Asia/Karachi).",
    "daily_cap_reached": "Today's business-initiated cap is reached.",
    "contact_frequency_cap": "This contact was messaged within the last 7 days.",
}


def _active(db: Session, org: uuid.UUID, user_id: uuid.UUID | None) -> bool:
    if user_id is None:
        return False
    return bool(db.scalar(select(User.active).where(User.organization_id == org, User.id == user_id)))


def decide(
    db: Session,
    *,
    org: uuid.UUID,
    now: datetime,
    settings: Settings,
    contact_id: uuid.UUID,
    purpose: policy.Purpose,
    campaign_id: uuid.UUID | None,
    template_ref: str | None,
    inbound_ref: str | None,
) -> dict[str, Any]:
    """A read-only reading (no audit, no commit). Callers that act on it re-read; it is never cached."""
    contact = contacts.get(db, org, contact_id)
    account = db.scalar(select(Account).where(Account.organization_id == org, Account.id == contact.account_id))
    if account is None:  # pragma: no cover  # composite FK
        raise NotFound()
    fixtures_allowed = settings.environment != "production" and evaluation.provenance(db, org, account) == "synthetic"

    campaign_status: str | None = None
    campaign_blockers: tuple[str, ...] = ()
    owner: uuid.UUID | None = contact.created_by if purpose == "service_reply" else None
    if campaign_id is not None:
        campaign = campaign_service._campaign(db, org, campaign_id)
        member = drafts._membership(db, org, campaign.id, account.id)
        campaign_status = campaign.status
        campaign_blockers = tuple(drafts.blockers(db, campaign, member, account, now, settings.environment))
        if purpose != "service_reply":
            owner = member.decided_by if member is not None and member.stage != "excluded" else None

    template_blocker, template = None, None
    if template_ref is not None:
        entry = fixtures.template(template_ref) if template_ref.startswith(fixtures.PREFIX) else None
        if template_ref.startswith(fixtures.PREFIX) and not fixtures_allowed:
            template_blocker = FIXTURE_BLOCKER
        elif entry is not None:
            template = policy.TemplateFact(template_ref, True, entry["provider_status"], entry["category"])
        else:  # operator-entered or unknown: never provider-approved
            template = policy.TemplateFact(template_ref, False, "unknown", "unknown")

    inbound_blocker, inbound = None, None
    if inbound_ref is not None:
        message = fixtures.inbound(inbound_ref)
        if not fixtures_allowed:
            inbound_blocker = FIXTURE_BLOCKER
        elif message is None:
            inbound_blocker = "no_inbound_context"
        else:
            key = dict(contacts.keyring(settings).keys).get(contact.key_id)
            matches = key is not None and addresses.digest(key, message["address"]) == contact.address_digest
            inbound = policy.InboundFact(inbound_ref, message["received_at"], matches)

    permissions = tuple(
        policy.PermissionFact(
            str(p.id),
            p.status,
            p.purpose,
            p.channel,
            p.business_name,
            p.consent_wording_version,
            p.captured_at,
            p.expires_at,
            p.version,
        )
        for p in contacts.permissions(db, contact)
    )
    inputs = policy.Inputs(
        purpose=purpose,
        now=now,
        kill_switch=settings.outreach_kill_switch,
        suppressed=contacts.suppression(db, contact) is not None,
        permissions=permissions,
        campaign_status=campaign_status,
        campaign_blockers=campaign_blockers,
        template=template,
        template_blocker=template_blocker,
        inbound=inbound,
        inbound_blocker=inbound_blocker,
        human_owner_active=_active(db, org, owner),
        usage=policy.Usage(),
    )
    decision = policy.evaluate(inputs)
    suppression_revision = contacts.suppression_revision(db, org)
    input_digest = hashlib.sha256(
        json.dumps(
            {
                "contact": str(contact.id),
                "purpose": purpose,
                "campaign": str(campaign_id) if campaign_id else None,
                "template": template_ref,
                "inbound": inbound_ref,
                "permissions": [(p.id, p.status, p.version) for p in permissions],
                "suppression_revision": suppression_revision,
                "campaign_status": campaign_status,
                "campaign_blockers": campaign_blockers,
                "policy": policy.POLICY_VERSION,
                "at": now.isoformat(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "decision": decision.decision,
        "reasons": [{"code": r, "explanation": EXPLANATIONS.get(r, r)} for r in decision.reasons],
        "channel": "whatsapp",
        "purpose": purpose,
        "contact_id": str(contact.id),
        "address": contact.address_hint,
        "campaign_id": str(campaign_id) if campaign_id else None,
        "policy_version": decision.policy_version,
        "permission_revision": (
            {"id": decision.permission_id, "version": decision.permission_version} if decision.permission_id else None
        ),
        "suppression_revision": suppression_revision,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "next_window_at": decision.next_window_at.isoformat() if decision.next_window_at else None,
        "input_digest": input_digest,
        "live_send_authorized": decision.live_send_authorized,
        "reusable": False,
        "notice": NOTICE,
    }


def evaluate(
    db: Session,
    *,
    actor: Actor,
    clock: Clock,
    settings: Settings,
    contact_id: uuid.UUID,
    purpose: policy.Purpose,
    campaign_id: uuid.UUID | None,
    template_ref: str | None,
    inbound_ref: str | None,
) -> dict[str, Any]:
    """`decide`, audited (actor, decision, reasons, input digest, policy version; never an address or proof)."""
    account_service._require(actor, Capability.MUTATE)
    result = decide(
        db,
        org=actor.organization_id,
        now=clock.now(),
        settings=settings,
        contact_id=contact_id,
        purpose=purpose,
        campaign_id=campaign_id,
        template_ref=template_ref,
        inbound_ref=inbound_ref,
    )
    management._audit(
        db,
        actor,
        clock,
        "channel_eligibility.evaluated",
        contact_id,
        {
            "decision": result["decision"],
            "reasons": [r["code"] for r in result["reasons"]],
            "purpose": purpose,
            "campaign_id": result["campaign_id"],
            "policy_version": result["policy_version"],
            "input_digest": result["input_digest"],
            "live_send_authorized": False,
        },
        target_type="contact",
    )
    db.commit()
    return result
