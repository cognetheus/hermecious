# ruff: noqa: F401, F811  # the P5.4 inbox fixtures are imported and requested by name
"""P6.3 acceptance OWNER-01..08/10 (API + real Postgres + a fake transport). Nothing here can send.

The dispatch fence's "allow" path needs a reply approval that does not exist before P6.5, so tests substitute
`fence.APPROVAL` (a documented seam); `test_owner_06_…` proves the real default denies.
"""

import json
import threading
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.accounts import management
from app.auth.models import Role
from app.auth.service import Actor
from app.contacts.models import Contact
from app.conversations import fence
from app.conversations import service as conversations
from app.conversations.models import ConversationOwner, ConversationOwnerEvent, DispatchAttempt, HandoffTask
from app.core.errors import Conflict, Forbidden
from app.core.settings import Settings
from app.intent import classifier
from app.replies.models import ReplyProposalRow
from tests.integration.auth_helpers import add_user, db, logged_in, mutation_headers
from tests.integration.test_campaigns import plain_account
from tests.integration.test_eligibility import add_contact, suppress
from tests.integration.test_inbox import API, CONTENT_KEY, inbound, no_egress, only_thread, operator, org, owner
from tests.integration.test_qualification import publish_offer
from tests.integration.test_research import Org
from tests.integration.test_whatsapp_test_sends import configure
from tests.integration.test_whatsapp_webhook import KNOWN, drain

pytestmark = pytest.mark.usefixtures("app")


@pytest.fixture(autouse=True)
def worker_content_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMECIOUS_INBOUND_CONTENT_SECRETS", CONTENT_KEY.get_secret_value())


class Conversation:
    """A known contact's signed message, its thread and a grounded P6.2 draft."""

    def __init__(self, app: FastAPI, client: TestClient, org: Org, operator: str) -> None:
        self.app, self.client, self.org, self.operator = app, client, org, operator
        configure(app, inbound_content_secrets=CONTENT_KEY, reply_proposals="fixtures")
        publish_offer(app, org)
        school = plain_account(app, org, "Owned School (Synthetic)")
        self.contact = add_contact(client, operator, school, "+" + KNOWN).json()["id"]
        inbound(client, "wamid.SYNOWNER0001", sender=KNOWN, body="fees module hai?")
        drain(app)
        self.thread = only_thread(client)["id"]
        (entry,) = client.get(f"{API}/threads/{self.thread}").json()["entries"]
        self.message = entry["id"]
        made = client.post(f"{API}/messages/{self.message}/reply-proposals", json={},
                           headers=mutation_headers(operator))  # fmt: skip
        assert made.status_code == 201, made.text
        self.proposal = made.json()["id"]

    def state(self, client: TestClient | None = None) -> dict[str, Any]:
        found: dict[str, Any] = (client or self.client).get(f"{API}/threads/{self.thread}/ownership").json()
        return found

    def run(
        self, command: str, *, client: TestClient | None = None, csrf: str | None = None, revision: int | None = None,
        key: str | None = None, reason: str = "manual", **extra: Any,
    ) -> Any:  # fmt: skip
        c, token = (client, csrf) if client is not None else (self.client, self.operator)
        body = {"command": command, "expected_revision": revision or self.state(c)["revision"], "reason": reason,
                "idempotency_key": key or f"own-{uuid.uuid4().hex[:12]}", **extra}  # fmt: skip
        return c.post(f"{API}/threads/{self.thread}/ownership", json=body, headers=mutation_headers(token or ""))

    def to_agent(self) -> None:
        assert self.run("takeover", reason="operator_takeover").status_code == 200
        assert self.run("release_to_agent", reason="agent_release_approved").json()["state"] == "agent_owned"

    def enqueue(self, key: str | None = None) -> uuid.UUID:
        with db(self.app) as session:
            connection = session.scalar(text("SELECT id FROM provider_connections LIMIT 1"))
            attempt = fence.enqueue(
                session, org=self.org.id, thread_id=uuid.UUID(self.thread), reply_proposal_id=uuid.UUID(self.proposal),
                contact_id=uuid.UUID(self.contact), connection_id=connection, purpose="service_reply",
                trace_id="trace-test", idempotency_key=key or f"att-{uuid.uuid4().hex[:12]}",
                now=self.app.state.clock.now(),
            )  # fmt: skip
            return attempt.id

    def check(self, attempt: uuid.UUID, generation: int, settings: Settings | None = None) -> fence.Decision:
        with db(self.app) as session:
            return fence.final_check(session, org=self.org.id, attempt_id=attempt, expected_generation=generation,
                                     settings=settings or live(self.app), now=self.app.state.clock.now())  # fmt: skip

    def attempt(self, attempt: uuid.UUID) -> DispatchAttempt:
        with db(self.app) as session:
            row = session.get(DispatchAttempt, attempt)
            assert row is not None
            return row


def live(app: FastAPI, **over: Any) -> Settings:
    """A production-shaped settings copy given only to the fence (the app itself stays in test mode)."""
    settings: Settings = app.state.settings.model_copy(update={
        "environment": "production", "whatsapp_mode": "production", "live_outbound_enabled": True,
        "build_sha": "0123abc", **over,
    })  # fmt: skip
    return settings


class FakeTransport:
    def __init__(self, outcome: str = "accepted", timeout: bool = False) -> None:
        self.calls: list[uuid.UUID] = []
        self.outcome, self.timeout = outcome, timeout

    def submit(self, attempt_id: uuid.UUID) -> str:
        self.calls.append(attempt_id)
        if self.timeout:
            raise TimeoutError
        return self.outcome


@pytest.fixture
def conv(app: FastAPI, client: TestClient, org: Org, operator: str) -> Conversation:
    return Conversation(app, client, org, operator)


@pytest.fixture
def approved(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEST SEAM: P6.5 will own reply approval; here every current draft counts as approved."""
    monkeypatch.setattr(fence, "APPROVAL", lambda _proposal: True)


# --- OWNER-01 / OWNER-02 -------------------------------------------------------------------------------------------


def test_owner_01_02_one_canonical_owner_and_an_atomic_audited_takeover(
    app: FastAPI, client: TestClient, conv: Conversation, no_egress: list[str]
) -> None:
    first = conv.state()
    assert (first["state"], first["owner_type"], first["owner_generation"], first["auto_replies"]) == (
        "new", "none", 0, "disabled",
    )  # fmt: skip
    observer = TestClient(app, raise_server_exceptions=False)
    observer_csrf = logged_in(observer, "observer@r.example")
    assert conv.state(observer)["state"] == "new"  # observers can read
    assert conv.run("pause", client=observer, csrf=observer_csrf).status_code == 403
    no_csrf = client.post(f"{API}/threads/{conv.thread}/ownership", json={
        "command": "pause", "expected_revision": conv.state()["revision"], "reason": "manual",
        "idempotency_key": "own-nocsrf-0001"})  # fmt: skip
    assert no_csrf.status_code == 403
    assert conv.run("takeover", reason="operator_takeover").status_code == 200
    assert conv.run("block", reason="manual").status_code == 403  # block/reopen are owner-only
    state = conv.state()
    assert (state["state"], state["owner_type"], state["owner"], state["owner_generation"]) == (
        "human_owned", "human", "operator user", 1,
    )  # fmt: skip
    assert state["handoff"]["reason"] == "operator_takeover" and state["handoff"]["assigned_to"] == "operator user"
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(ConversationOwner)) == 1
        audits = text("SELECT count(*) FROM action_audits WHERE action_type = 'conversation.takeover'")
        assert session.scalar(audits) == 1
        with pytest.raises(DBAPIError):  # the generation can never go backwards, whatever the code path
            session.execute(text("UPDATE conversation_owners SET owner_generation = 0"))
            session.commit()
    with db(app) as session, pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM conversation_owner_events"))
        session.commit()
    assert no_egress == []


# --- OWNER-03 ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["takeover", "pause", "block", "resolve"])
def test_owner_03_human_paused_blocked_or_resolved_denies_queued_and_new_attempts(
    app: FastAPI, conv: Conversation, owner: tuple[TestClient, str], approved: None, command: str
) -> None:
    conv.to_agent()
    generation = conv.state()["owner_generation"]
    queued = conv.enqueue()
    client, csrf = owner if command == "block" else (conv.client, conv.operator)
    changed = conv.run(command, client=client, csrf=csrf, reason="manual")
    assert changed.status_code == 200, changed.text
    assert conv.attempt(queued).state == "canceled" and conv.attempt(queued).deny_reason == "owner_changed"
    assert changed.json()["history"][-1]["canceled_attempts"] == 1  # fenced inside the same commit
    denied = conv.check(queued, generation)
    assert not denied.allow and denied.reasons == ["attempt_canceled"]
    fresh = conv.enqueue()  # queued under the new generation, but the agent no longer owns the conversation
    decision = conv.check(fresh, conv.state()["owner_generation"])
    assert not decision.allow and decision.reasons[0].startswith("owner_")


# --- OWNER-04 ------------------------------------------------------------------------------------------------------


def test_owner_04_competing_operators_conflict_and_assignees_are_validated(
    app: FastAPI, org: Org, conv: Conversation
) -> None:
    add_user(app, org.id, "operator2@r.example", role=Role.OPERATOR)
    revision = conv.state()["revision"]
    results: list[int] = []
    barrier = threading.Barrier(2)

    def race(email: str) -> None:
        local = TestClient(app, raise_server_exceptions=False)
        csrf = logged_in(local, email)
        barrier.wait(timeout=10)
        results.append(conv.run("takeover", client=local, csrf=csrf, revision=revision,
                                reason="operator_takeover").status_code)  # fmt: skip

    racers = [threading.Thread(target=race, args=(e,)) for e in ("operator@r.example", "operator2@r.example")]
    for t in racers:
        t.start()
    for t in racers:
        t.join(timeout=30)
    assert sorted(results) == [200, 409]  # exactly one wins; never last-writer-wins
    assert conv.state()["owner_generation"] == 1
    inactive = add_user(app, org.id, "gone@r.example", role=Role.OPERATOR)
    with db(app) as session:
        session.execute(text("UPDATE users SET active = false WHERE id = :u"), {"u": inactive})
        session.commit()
    other = Org(app, "Assignee Org", prefix="s")
    for assignee in (inactive, other.owner, uuid.uuid4()):
        refused = conv.run("assign", assignee_id=str(assignee), reason="manual")
        assert refused.status_code == 422, assignee
    assert conv.run("assign", assignee_id=str(org.owner), reason="manual").json()["owner_user_id"] == str(org.owner)


# --- OWNER-05 ------------------------------------------------------------------------------------------------------


def test_owner_05_replays_crashes_and_restarts_never_revert_or_duplicate(
    app: FastAPI, conv: Conversation, monkeypatch: pytest.MonkeyPatch
) -> None:
    revision = conv.state()["revision"]
    real_audit = management._audit

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("worker killed before commit")

    monkeypatch.setattr(management, "_audit", crash)
    assert conv.run("takeover", revision=revision, key="own-crash-0001", reason="operator_takeover").status_code == 500
    assert (conv.state()["state"], conv.state()["owner_generation"]) == ("new", 0)  # nothing half-applied
    monkeypatch.setattr(management, "_audit", real_audit)
    once = conv.run("takeover", revision=revision, key="own-crash-0001", reason="operator_takeover")
    again = conv.run("takeover", revision=revision, key="own-crash-0001", reason="operator_takeover")
    assert (once.json()["applied"], again.json()["applied"]) == (True, False)  # double click: one logical result
    assert again.json()["owner_generation"] == 1
    changed = conv.run("takeover", revision=revision, key="own-crash-0001", reason="manual")
    assert changed.status_code == 409  # same key, altered content
    stale = conv.run("pause", revision=revision, reason="manual")
    assert stale.status_code == 409 and "reload" in stale.json()["error"]["message"]
    assert conv.run("open_handoff", reason="human_requested").status_code == 409  # one active task only
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(HandoffTask)) == 1
        events = session.scalar(select(func.count()).select_from(ConversationOwnerEvent))
    assert events == 1
    drain(app)  # a restart/replay of the inbox processor cannot touch ownership
    inbound(conv.client, "wamid.SYNOWNER0001", sender=KNOWN, body="fees module hai?")  # redelivery
    drain(app)
    assert (conv.state()["state"], conv.state()["owner_generation"]) == ("human_owned", 1)


# --- OWNER-06 ------------------------------------------------------------------------------------------------------


def test_owner_06_only_an_explicit_human_release_changes_ownership_and_it_grants_nothing(
    app: FastAPI, org: Org, conv: Conversation
) -> None:
    assert conv.run("takeover", reason="operator_takeover").status_code == 200
    machine = Actor(user_id=org.owner, organization_id=org.id, role=Role.OWNER, session_id=uuid.uuid4(), verifier="")
    with db(app) as session, pytest.raises(Forbidden):  # a job, classifier or model has no interactive session
        conversations.command(session, actor=machine, clock=app.state.clock, thread_id=uuid.UUID(conv.thread),
                              name="release_to_agent", expected_revision=conv.state()["revision"],
                              reason="agent_release_approved", idempotency_key="own-machine-0001")  # fmt: skip
    forged = conv.run("release_to_agent", reason="agent_release_approved", owner_generation=99)
    assert forged.status_code == 422  # a tampered generation is not even accepted as input
    released = conv.run("release_to_agent", reason="agent_release_approved")
    assert released.json()["state"] == "agent_owned"
    decision = conv.check(conv.enqueue(), released.json()["owner_generation"])
    assert not decision.allow and decision.reasons == ["reply_not_approved"]  # release is not permission


# --- OWNER-07 ------------------------------------------------------------------------------------------------------


def test_owner_07_suppression_kill_switch_live_gate_and_stale_drafts_outrank_agent_ownership(
    app: FastAPI, conv: Conversation, owner: tuple[TestClient, str], approved: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    conv.to_agent()
    generation = conv.state()["owner_generation"]
    allowed = conv.check(conv.enqueue(), generation)
    assert allowed.allow, allowed.reasons  # the baseline: everything holds
    assert not (d := conv.check(conv.enqueue(), generation, live(app, outreach_kill_switch=True))).allow
    assert "kill_switch_engaged" in d.reasons
    assert not (d := conv.check(conv.enqueue(), generation, app.state.settings)).allow  # test env: gate closed
    assert d.reasons and d.reasons[0].startswith("live_gate_")
    assert suppress(conv.client, conv.operator, conv.contact).status_code == 201  # an opt-out lands mid-draft
    d = conv.check(conv.enqueue(), generation)
    assert not d.allow and "eligibility_suppressed" in d.reasons
    monkeypatch.setattr(classifier, "CLASSIFIER_VERSION", "intent-rules-9.9")  # the draft's inputs change
    owner_client, csrf = owner
    owner_client.post(f"{API}/intent/backfill", headers=mutation_headers(csrf))
    drain(app)
    d = conv.check(conv.enqueue(), generation)
    assert not d.allow and d.reasons == ["reply_not_current"]


# --- OWNER-08 / OWNER-10 -------------------------------------------------------------------------------------------


def test_owner_08_10_submitted_before_takeover_is_kept_and_queued_after_is_denied(
    app: FastAPI, conv: Conversation, approved: None, no_egress: list[str]
) -> None:
    conv.to_agent()
    generation = conv.state()["owner_generation"]
    before = conv.enqueue()
    assert conv.check(before, generation).allow  # the fence point committed first
    queued = conv.enqueue()
    assert conv.run("takeover", reason="operator_takeover").status_code == 200  # then the takeover commits
    transport = FakeTransport("accepted")
    with db(app) as session:
        assert fence.submit(session, org=conv.org.id, attempt_id=before, transport=transport,
                            now=app.state.clock.now()) == "accepted"  # fmt: skip
    assert conv.attempt(queued).state == "canceled" and transport.calls == [before]
    attempts = {a["id"]: a for a in conv.state()["attempts"]}
    assert attempts[str(before)]["submitted_before_takeover"] is True and attempts[str(before)]["state"] == "accepted"
    assert attempts[str(queued)]["submitted_before_takeover"] is False
    conv.run("release_to_agent", reason="agent_release_approved")
    remembered = conv.check(conv.enqueue(), generation)  # a caller still holding the pre-takeover generation
    assert not remembered.allow and remembered.reasons == ["owner_generation_mismatch"]
    late = conv.enqueue()
    assert conv.check(late, conv.state()["owner_generation"]).allow
    timeout = FakeTransport(timeout=True)
    with db(app) as session:
        assert fence.submit(session, org=conv.org.id, attempt_id=late, transport=timeout,
                            now=app.state.clock.now()) == "indeterminate"  # fmt: skip
        with pytest.raises(Conflict):  # an indeterminate attempt is never resubmitted
            fence.submit(session, org=conv.org.id, attempt_id=late, transport=timeout, now=app.state.clock.now())
    assert len(timeout.calls) == 1 and no_egress == []
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(Contact)) == 1  # no contact was invented


@pytest.mark.parametrize("first", ["final_check", "takeover"])
def test_owner_10_real_concurrency_linearizes_takeover_and_the_final_check(
    app: FastAPI, conv: Conversation, approved: None, first: str
) -> None:
    conv.to_agent()
    generation, revision = conv.state()["owner_generation"], conv.state()["revision"]
    attempt = conv.enqueue()
    started, gate = threading.Event(), threading.Event()
    outcome: dict[str, Any] = {}
    real_reasons = fence._reasons

    def slow_reasons(*args: Any, **kwargs: Any) -> list[str]:  # hold the FOR SHARE lock while the takeover waits
        started.set()
        gate.wait(timeout=10)
        return real_reasons(*args, **kwargs)

    def check() -> None:
        outcome["decision"] = conv.check(attempt, generation)

    def takeover() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        csrf = logged_in(local, "operator@r.example")
        outcome["takeover"] = conv.run("takeover", client=local, csrf=csrf, revision=revision,
                                       reason="operator_takeover").status_code  # fmt: skip

    if first == "final_check":
        fence._reasons = slow_reasons
        try:
            a = threading.Thread(target=check)
            a.start()
            started.wait(timeout=10)
            b = threading.Thread(target=takeover)
            b.start()
            gate.set()
            a.join(timeout=30)
            b.join(timeout=30)
        finally:
            fence._reasons = real_reasons
        assert outcome["decision"].allow and outcome["takeover"] == 200
        assert conv.attempt(attempt).state == "submitting"  # submitted before the takeover: kept, never "unsent"
    else:
        takeover()
        check()
        assert outcome["takeover"] == 200 and not outcome["decision"].allow
        assert conv.attempt(attempt).state == "canceled"  # the takeover fenced it before any submission
    assert json.dumps(conv.state()["history"])  # history is intact either way
