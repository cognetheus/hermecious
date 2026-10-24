"""`eligibility-policy-1.0`: deterministic WhatsApp channel-eligibility rules (P4.3, ADR-022). Pure; no I/O.

The result is `allow_for_simulation`, `deny` or `defer`, with reason codes in precedence order:

1. kill switch, campaign paused or cancelled;
2. suppression (opt-out dominates everything);
3. a verified, explicit opt-in for this business, channel and purpose (business-initiated only);
4. scope: purpose, business and channel;
5. proof freshness: expiry, age, future dating, consent wording version;
6. template (business-initiated) or the 24-hour inbound service window (service replies);
7. campaign state and the evidence-quality gate;
8. an active human owner;
9. business hours (Asia/Karachi), then daily and per-contact caps: these only `defer`.

Every deny reason found is reported; `defer` applies only when nothing denies. `live_send_authorized` is always
False: a decision is a reading at `evaluated_at`, never a reusable authorization.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal

from app.core.clock import BUSINESS_TZ

POLICY_VERSION = "eligibility-policy-1.0"
BUSINESS_NAME = "CoderzHunt"
CHANNELS = ("whatsapp",)
PURPOSES = ("marketing", "utility", "service_reply")
CONSENT_WORDING = {
    "marketing": "optin-whatsapp-marketing-en-PK-v1",
    "utility": "optin-whatsapp-utility-en-PK-v1",
}
SERVICE_WINDOW = timedelta(hours=24)
PROOF_MAX_AGE = timedelta(days=365)
WORK_DAYS = frozenset(range(6))  # Monday..Saturday
WORK_START, WORK_END = time(9, 0), time(18, 0)
DAILY_CAP = 20  # business-initiated decisions per organization per Asia/Karachi day
CONTACT_MIN_GAP = timedelta(days=7)

Purpose = Literal["marketing", "utility", "service_reply"]
Outcome = Literal["allow_for_simulation", "deny", "defer"]


@dataclass(frozen=True)
class PermissionFact:
    id: str
    status: str
    purpose: str
    channel: str
    business_name: str
    consent_wording_version: str
    captured_at: datetime
    expires_at: datetime
    version: int


@dataclass(frozen=True)
class TemplateFact:
    ref: str
    verified_fixture: bool  # True only for a signed synthetic fixture usable here (never operator-entered)
    provider_status: str  # approved | pending | rejected | unknown
    category: str  # marketing | utility | unknown


@dataclass(frozen=True)
class InboundFact:
    ref: str
    received_at: datetime
    matches_contact: bool


@dataclass(frozen=True)
class Usage:
    org_business_initiated_today: int = 0
    contact_last_business_initiated_at: datetime | None = None


@dataclass(frozen=True)
class Inputs:
    purpose: Purpose
    now: datetime
    kill_switch: bool
    suppressed: bool
    permissions: tuple[PermissionFact, ...] = ()
    campaign_status: str | None = None
    campaign_blockers: tuple[str, ...] = ()
    template: TemplateFact | None = None
    template_blocker: str | None = None
    inbound: InboundFact | None = None
    inbound_blocker: str | None = None
    human_owner_active: bool = False
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class Decision:
    decision: Outcome
    reasons: tuple[str, ...]
    policy_version: str
    evaluated_at: datetime
    permission_id: str | None
    permission_version: int | None
    next_window_at: datetime | None = None

    @property
    def live_send_authorized(self) -> bool:
        return False


def _permission(i: Inputs, deny: list[str]) -> PermissionFact | None:
    channel = [p for p in i.permissions if p.channel == "whatsapp"]
    same = [p for p in channel if p.purpose == i.purpose]
    verified = next((p for p in same if p.status == "verified"), None)
    if verified is not None:
        return verified
    if any(p.status == "pending" for p in same):
        deny.append("permission_unverified")
    elif any(p.status == "revoked" for p in same):
        deny.append("permission_revoked")
    elif any(p.status == "verified" for p in channel):
        deny.append("purpose_not_covered")
    else:
        deny.append("no_opt_in_permission")
    return None


def _scope_and_freshness(p: PermissionFact, i: Inputs, deny: list[str]) -> None:
    if p.business_name != BUSINESS_NAME:
        deny.append("wrong_business")
    if p.expires_at <= i.now:
        deny.append("permission_expired")
    if p.captured_at > i.now:
        deny.append("proof_future_dated")
    elif i.now - p.captured_at > PROOF_MAX_AGE:
        deny.append("proof_stale")
    if p.consent_wording_version != CONSENT_WORDING.get(i.purpose):
        deny.append("consent_wording_outdated")


def _template(i: Inputs, deny: list[str]) -> None:
    t = i.template
    if i.template_blocker:
        deny.append(i.template_blocker)
    elif t is None:
        deny.append("template_missing")
    elif not t.verified_fixture or t.provider_status == "pending":
        deny.append("template_unverified")  # operator-entered template state is never provider approval
    elif t.provider_status != "approved":
        deny.append("template_rejected")
    elif t.category != i.purpose:
        deny.append("template_wrong_category")


def _service_window(i: Inputs, deny: list[str]) -> None:
    if i.inbound_blocker:
        deny.append(i.inbound_blocker)
    elif i.inbound is None:
        deny.append("no_inbound_context")
    elif not i.inbound.matches_contact:
        deny.append("inbound_context_mismatch")
    elif i.inbound.received_at > i.now:
        deny.append("inbound_context_invalid")
    elif i.now - i.inbound.received_at >= SERVICE_WINDOW:
        deny.append("service_window_closed")


def next_open(at: datetime) -> datetime:
    """The first instant at or after `at` inside business hours (Asia/Karachi), returned in UTC."""
    local = at.astimezone(BUSINESS_TZ)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in WORK_DAYS:
            continue
        start = datetime.combine(day, WORK_START, BUSINESS_TZ)
        end = datetime.combine(day, WORK_END, BUSINESS_TZ)
        if local < end:
            return max(local, start).astimezone(at.tzinfo)
    raise AssertionError("no business day within a week")  # pragma: no cover


def evaluate(i: Inputs) -> Decision:
    deny: list[str] = []
    business_initiated = i.purpose != "service_reply"
    # 1. kill switch and campaign pause
    if i.kill_switch:
        deny.append("kill_switch_engaged")
    if i.campaign_status in ("paused", "cancelled"):
        deny.append(f"campaign_{i.campaign_status}")
    # 2. suppression dominates every campaign and purpose
    if i.suppressed:
        deny.append("suppressed")
    permission = None
    if business_initiated:
        # 3-5. verified explicit opt-in, scope and proof freshness
        permission = _permission(i, deny)
        if permission is not None:
            _scope_and_freshness(permission, i, deny)
        # 6. provider-approved template (synthetic fixture only until P5)
        _template(i, deny)
        # 7. campaign state and the evidence-quality gate
        if i.campaign_status is None:
            deny.append("campaign_required")
    else:
        # 6. free-form service reply: official inbound context within 24 hours; never marketing consent
        _service_window(i, deny)
    deny.extend(i.campaign_blockers)  # 7. (a service reply is checked against a campaign only if one is named)
    # 8. an accountable human owner
    if not i.human_owner_active:
        deny.append("no_active_human_owner")
    pid, pver = (permission.id, permission.version) if permission else (None, None)
    if deny:
        return Decision("deny", tuple(dict.fromkeys(deny)), POLICY_VERSION, i.now, pid, pver)
    # 9. business hours and caps only defer
    defer: list[str] = []
    candidates = [i.now]
    if business_initiated:
        if next_open(i.now) != i.now:
            defer.append("outside_business_hours")
        if i.usage.org_business_initiated_today >= DAILY_CAP:
            defer.append("daily_cap_reached")
            tomorrow = (i.now.astimezone(BUSINESS_TZ) + timedelta(days=1)).date()
            candidates.append(datetime.combine(tomorrow, time(0), BUSINESS_TZ).astimezone(i.now.tzinfo))
        last = i.usage.contact_last_business_initiated_at
        if last is not None and i.now - last < CONTACT_MIN_GAP:
            defer.append("contact_frequency_cap")
            candidates.append(last + CONTACT_MIN_GAP)
    if defer:
        return Decision("defer", tuple(defer), POLICY_VERSION, i.now, pid, pver, next_open(max(candidates)))
    return Decision("allow_for_simulation", (), POLICY_VERSION, i.now, pid, pver)
