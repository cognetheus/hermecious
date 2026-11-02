"""P5.4 acceptance INBOX-01..10 (API + Postgres + the P1.5 runner). Read-only inbox over signed P5.2/P5.3 facts.

Inbound events are signed locally with a test secret (P5.2 path). Test sends go through the real P5.3 confirm path
against the in-process fake Graph layer. Synthetic, zero-filled numbers only; nothing can reach Meta.
"""

import base64
import json
import threading
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.accounts.models import Account
from app.contacts.models import Contact
from app.egress import https_client
from app.inbox import service as inbox
from app.inbox.models import InboxThread
from app.whatsapp import service as connections
from app.whatsapp import test_sends
from app.whatsapp.models import ProviderEventItem
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_campaigns import plain_account
from tests.integration.test_eligibility import add_contact
from tests.integration.test_research import Org, worker
from tests.integration.test_whatsapp_test_sends import TEST_DIGITS, TEST_NUMBER, WAMID, FakeGraph, Flow, configure
from tests.integration.test_whatsapp_webhook import (
    KNOWN,
    PHONE,
    STRANGER,
    change,
    drain,
    envelope,
    message,
    post,
    status,
)

pytestmark = pytest.mark.usefixtures("app")
API = "/api/v1/inbox/whatsapp"
CONTENT_KEY = SecretStr("c1:" + "synthetic-inbound-content-key-0123456789")


@pytest.fixture
def org(app: FastAPI) -> Org:
    configure(app, inbound_content_secrets=CONTENT_KEY)
    org = Org(app)
    with db(app) as session:
        connections.bind_connection(session, actor=org.actor, clock=app.state.clock, settings=app.state.settings)
    return org


@pytest.fixture
def owner(app: FastAPI, org: Org) -> tuple[TestClient, str]:
    client = TestClient(app, raise_server_exceptions=False)
    return client, logged_in(client, "owner@r.example")


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    fake = FakeGraph()
    monkeypatch.setattr(test_sends, "CONTRACT_HTTP", lambda _connection: fake)
    return fake


@pytest.fixture
def flow(app: FastAPI, owner: tuple[TestClient, str], client: TestClient, operator: str, graph: FakeGraph) -> Flow:
    return Flow(app, owner, client, operator)


@pytest.fixture
def no_egress(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any attempt to open a real provider connection is recorded and refused."""
    attempts: list[str] = []

    def refuse(self: Any, method: str, url: str, **_: Any) -> Any:
        attempts.append(f"{method} {url}")
        raise AssertionError("egress attempted")

    monkeypatch.setattr(https_client.PinnedHttpsClient, "request_json", refuse)
    return attempts


def inbound(client: TestClient, wamid: str, sender: str = STRANGER, body: str | None = "hello", **kw: Any) -> Any:
    response = post(client, envelope(change(messages=(message(wamid, sender=sender, text=body, **kw),))))
    assert response.status_code == 200, response.text
    return response


def threads(client: TestClient, **params: Any) -> Any:
    return client.get(f"{API}/threads", params=params)


def only_thread(client: TestClient) -> dict[str, Any]:
    (item,) = threads(client).json()["items"]
    found: dict[str, Any] = item
    return found


def detail(client: TestClient, thread_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"{API}/threads/{thread_id}", params=params)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def snapshot(app: FastAPI, versions: bool = True) -> list[tuple[Any, ...]]:
    with db(app) as session:
        return [
            (t.party_key_id, t.party_digest, t.party_hint, t.last_activity_at, t.last_inbound_seq,
             t.reviewed_through_seq, t.version if versions else None)
            for t in session.scalars(select(InboxThread).order_by(InboxThread.party_digest))
        ]  # fmt: skip


# --- INBOX-01 ------------------------------------------------------------------------------------------------------


def test_inbox_01_verified_inbound_becomes_one_thread_without_enrollment(
    app: FastAPI, client: TestClient, org: Org, operator: str, no_egress: list[str]
) -> None:
    with db(app) as session:
        accounts_before = session.scalar(select(func.count()).select_from(Account))
    inbound(client, "wamid.SYNINBOX0101", body="Assalam o alaikum, fees module ke baare mein batayein")
    drain(app)
    thread = only_thread(client)
    assert thread["party"] == {
        "type": "unmatched", "label": "Unmatched WhatsApp contact", "conflict": None, "address": "+92 ••••••• 555",
        "suppressed": False, "environment": "test",
    }  # fmt: skip
    assert (thread["unread"], thread["reviewed_through_seq"]) == (1, 0)
    (entry,) = detail(client, thread["id"])["entries"]
    assert (entry["type"], entry["provenance"], entry["content"]) == ("inbound", "verified_inbound", "available")
    assert entry["text"] == "Assalam o alaikum, fees module ke baare mein batayein"
    with db(app) as session:  # no lead, contact or account is created from an inbound message
        assert session.scalar(select(func.count()).select_from(Contact)) == 0
        assert session.scalar(select(func.count()).select_from(Account)) == accounts_before
    configure(app, inbound_content_secrets=None)  # without a content key nothing is kept (P5.2 minimization)
    inbound(client, "wamid.SYNINBOX0102", body="second", minutes_ago=1)
    drain(app)
    entries = detail(client, thread["id"])["entries"]
    assert [e["content"] for e in entries] == ["unreadable", "not_retained"]  # no key: nothing can be shown
    assert no_egress == []


# --- INBOX-02 ------------------------------------------------------------------------------------------------------


def test_inbox_02_duplicates_and_racing_first_arrivals_create_one_thread(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    inbound(client, "wamid.SYNINBOX0201")
    inbound(client, "wamid.SYNINBOX0201")  # same envelope again
    batch = envelope(change(messages=(message("wamid.SYNINBOX0201", sender=STRANGER),
                                      message("wamid.SYNINBOX0202", sender=STRANGER))))  # fmt: skip
    assert post(client, batch).json()["accepted"] == 1  # different envelope, same provider message id
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def race(name: str) -> None:
        barrier.wait(timeout=10)
        outcomes.extend(o.status for o in worker(app, name).run_once())

    workers = [threading.Thread(target=race, args=(f"worker-{i}",)) for i in range(2)]
    for t in workers:
        t.start()
    for t in workers:
        t.join(timeout=60)
    drain(app)
    thread = only_thread(client)
    assert thread["unread"] == 2 and len(detail(client, thread["id"])["entries"]) == 2
    inbound(client, "wamid.SYNINBOX0202")  # redelivery after processing
    drain(app)
    assert only_thread(client)["unread"] == 2


# --- INBOX-03 / INBOX-08 -------------------------------------------------------------------------------------------


def test_inbox_03_08_test_send_statuses_reconcile_and_are_never_a_prospect(
    app: FastAPI, client: TestClient, org: Org, flow: Flow, graph: FakeGraph
) -> None:
    recipient, template = flow.ready()
    post(client, envelope(change(statuses=(status(WAMID, "delivered", 0.4),))))  # before Graph answered
    drain(app)
    created = flow.preview(recipient, template).json()
    assert flow.confirm(created).json()["state"] == "provider_accepted"
    for state, minutes in (("read", 0.2), ("sent", 0.5), ("failed", 0.1)):  # out of order, then a contradiction
        post(client, envelope(change(statuses=(status(WAMID, state, minutes),))))
        drain(app)
    app.state.clock.advance(timedelta(seconds=1))  # distinct confirmation times keep the order deterministic
    second = flow.preview(recipient, template, ["Again"]).json()
    graph.sends.append((200, FakeGraph.accepted("wamid.SYNTESTSEND000000009")))
    flow.confirm(second)  # accepted, no webhook ever arrives
    inbound(client, "wamid.SYNINBOX0301", sender=TEST_DIGITS, body="Received, thanks", minutes_ago=-0.5)
    drain(app)
    thread = only_thread(client)
    assert thread["party"]["type"] == "test_recipient" and thread["party"]["label"].startswith("TEST recipient")
    entries = detail(client, thread["id"])["entries"]
    assert [e["type"] for e in entries] == ["test_outbound", "test_outbound", "inbound"]
    first, unknown, reply = entries
    assert first["provenance"] == "provider_test" and first["delivery"] == {
        "status": "read", "conflict": "failed_after_delivered",
    }  # fmt: skip
    assert [s["status"] for s in first["statuses"]] == ["sent", "delivered", "read", "failed"]  # provider order
    assert unknown["delivery"] == {"status": "accepted_unknown_delivery", "conflict": None} and not unknown["statuses"]
    assert reply["text"] == "Received, thanks"
    # A sourced contact later created with the test number does not turn the test thread into a prospect.
    school = plain_account(app, org, "Test Number Collision School (Synthetic)")
    assert add_contact(client, flow.operator, school, TEST_NUMBER).status_code == 201
    party = only_thread(client)["party"]
    assert (party["type"], party["conflict"]) == ("test_recipient", "matches_sourced_contact")


# --- INBOX-04 ------------------------------------------------------------------------------------------------------


def test_inbox_04_crash_rollback_and_repeated_rebuild_keep_the_same_timeline(
    app: FastAPI, client: TestClient, org: Org, owner: tuple[TestClient, str], operator: str, no_egress: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip

    for n, sender in enumerate((STRANGER, KNOWN, STRANGER)):
        inbound(client, f"wamid.SYNINBOX040{n}", sender=sender, body=f"message {n}", minutes_ago=3 - n)
    real_touch = inbox.touch

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("worker killed mid-transaction")

    monkeypatch.setattr(inbox, "touch", crash)
    drain(app)  # every item fails inside its transaction: nothing half-applied
    with db(app) as session:
        assert session.scalar(select(func.count()).select_from(InboxThread)) == 0
        session.execute(text("UPDATE provider_event_items SET processing_status = 'pending', error_class = NULL"))
        session.commit()  # the operator re-queues the parked items (replay)
    monkeypatch.setattr(inbox, "touch", real_touch)
    post(client, envelope(change(messages=(message("wamid.SYNINBOX0409", sender=STRANGER),))))  # wakes the runner
    drain(app)
    before, snapshot_without_versions = snapshot(app), snapshot(app, versions=False)
    timelines = {t["id"]: detail(client, t["id"])["entries"] for t in threads(client).json()["items"]}
    assert len(before) == 2 and sum(len(e) for e in timelines.values()) == 4
    owner_client, csrf = owner
    for _ in range(2):  # rebuild twice: identical rows and versions
        assert owner_client.post(f"{API}/rebuild", headers=mutation_headers(csrf)).status_code == 202
        app.state.clock.advance(timedelta(seconds=1))
        drain(app)
        assert snapshot(app) == before
    with db(app) as session:  # a rebuild that is rolled back changes nothing
        connection_id = session.scalar(select(InboxThread.provider_connection_id).limit(1))
        assert connection_id is not None
        inbox.rebuild(session, org.id, connection_id, app.state.clock.now())
        session.rollback()
        session.execute(text("DELETE FROM inbox_threads"))  # the projection is lost entirely
        session.commit()
    assert owner_client.post(f"{API}/rebuild", headers=mutation_headers(csrf)).status_code == 202
    drain(app)
    assert snapshot(app, versions=False) == snapshot_without_versions
    rebuilt = {t["party"]["address"]: detail(client, t["id"])["entries"] for t in threads(client).json()["items"]}
    assert sorted(rebuilt.values(), key=len) == sorted(timelines.values(), key=len)
    assert no_egress == []


# --- INBOX-05 ------------------------------------------------------------------------------------------------------


def test_inbox_05_other_tenants_roles_and_sessions_cannot_read_or_mutate(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    inbound(client, "wamid.SYNINBOX0501")
    post(client, envelope(change(messages=(message("wamid.SYNINBOX0502"),)), waba="100000000000999"))  # wrong WABA
    post(client, envelope(change(messages=(message("wamid.SYNINBOX0503"),), phone="200000000000999")))  # unbound
    drain(app)
    thread = only_thread(client)
    other = Org(app, "Other Org", prefix="s")
    stranger = TestClient(app, raise_server_exceptions=False)
    csrf = logged_in(stranger, "owner@s.example")
    assert threads(stranger).json()["items"] == []
    assert stranger.get(f"{API}/threads/{thread['id']}").status_code == 404
    review = {"through_seq": thread["last_inbound_seq"]}
    assert stranger.post(f"{API}/threads/{thread['id']}/review", json=review,
                         headers=mutation_headers(csrf)).status_code == 404  # fmt: skip
    assert stranger.post(f"{API}/rebuild", headers=mutation_headers(csrf)).status_code == 404  # no connection
    assert other.id != org.id
    observer = TestClient(app, raise_server_exceptions=False)
    observer_csrf = logged_in(observer, "observer@r.example")
    assert threads(observer).status_code == 403 and observer.get(f"{API}/threads/{thread['id']}").status_code == 403
    assert observer.post(f"{API}/threads/{thread['id']}/review", json=review,
                         headers=mutation_headers(observer_csrf)).status_code == 403  # fmt: skip
    assert client.post(f"{API}/rebuild", headers=mutation_headers(operator)).status_code == 403  # owner only
    assert client.post(f"{API}/threads/{thread['id']}/review", json=review).status_code == 403  # no CSRF
    with db(app) as session:
        session.execute(text("UPDATE auth_sessions SET revoked_at = now()"))
        session.commit()
    assert threads(client).status_code == 401
    with db(app) as session:
        assert session.scalar(select(InboxThread.reviewed_through_seq)) == 0  # nothing was mutated


# --- INBOX-06 ------------------------------------------------------------------------------------------------------


def test_inbox_06_numbers_secrets_and_markup_are_never_exposed(
    app: FastAPI, client: TestClient, org: Org, operator: str, json_logs: Any
) -> None:
    hostile = '<script>alert("x")</script><img src=x onerror=alert(1)> call +923001234567 ' + "\ud800"
    inbound(client, "wamid.SYNINBOX0601", body=hostile)
    inbound(client, "wamid.SYNINBOX0602", body="روکیں نہیں، تفصیلات بھیجیں", minutes_ago=1)
    drain(app)
    thread = only_thread(client)
    response = client.get(f"{API}/threads/{thread['id']}")
    assert response.headers["cache-control"] == "private, no-store"
    first, urdu = response.json()["entries"]
    assert first["text"] == hostile.replace("\ud800", "�")  # returned as data, never rendered here
    assert urdu["text"] == "روکیں نہیں، تفصیلات بھیجیں"
    raw = response.text + threads(client).text
    assert STRANGER not in raw and f"+{STRANGER}" not in raw  # the sender number never leaves the server
    logged = json.dumps(json_logs(), default=str)
    assert "onerror" not in logged and STRANGER not in logged and "تفصیلات" not in logged
    with db(app) as session:
        stored = json.dumps([i.normalized_json for i in session.scalars(select(ProviderEventItem))], ensure_ascii=False)
        assert "onerror" not in stored and "تفصیلات" not in stored and STRANGER not in stored  # sealed only
        item = session.scalar(
            select(ProviderEventItem).where(ProviderEventItem.provider_message_id == "wamid.SYNINBOX0601")
        )
        assert item is not None
        sealed = dict(item.normalized_json["sealed_text"])
        ct = bytearray(base64.b64decode(sealed["ct"]))
        ct[0] ^= 1
        item.normalized_json = item.normalized_json | {"sealed_text": sealed | {"ct": base64.b64encode(ct).decode()}}
        moved = session.scalar(
            select(ProviderEventItem).where(ProviderEventItem.provider_message_id == "wamid.SYNINBOX0602")
        )
        assert moved is not None
        moved.normalized_json = moved.normalized_json | {"sealed_text": sealed}  # ciphertext moved to another message
        session.commit()
    assert [e["content"] for e in detail(client, thread["id"])["entries"]] == ["unreadable", "unreadable"]
    app.state.clock.advance(timedelta(days=91))
    client.cookies.clear()
    logged_in(client, "operator@r.example")
    assert [e["content"] for e in detail(client, thread["id"])["entries"]] == ["expired", "expired"]
    inbound(client, "wamid.SYNINBOX0603", body="new", minutes_ago=-(91 * 24 * 60) + 1)  # "now" on the moved clock
    drain(app)  # the processor purges sealed text past retention
    with db(app) as session:
        kept = [i.provider_message_id for i in session.scalars(select(ProviderEventItem))
                if "sealed_text" in i.normalized_json]  # fmt: skip
    assert kept == ["wamid.SYNINBOX0603"]


# --- INBOX-07 ------------------------------------------------------------------------------------------------------


def test_inbox_07_stable_pagination_ties_and_late_arrivals(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    senders = [f"92000000060{n}" for n in range(7)]
    for n, sender in enumerate(senders):  # identical provider timestamps on purpose
        inbound(client, f"wamid.SYNINBOX07{n:02}", sender=sender, minutes_ago=2)
    drain(app)
    seen: list[str] = []
    cursor = None
    while True:
        page = threads(client, limit=3, **({"cursor": cursor} if cursor else {})).json()
        seen += [t["id"] for t in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 7 and len(set(seen)) == 7
    assert [t["id"] for t in threads(client, limit=50).json()["items"]] == seen  # same order as the paged walk
    for n in range(5):  # one party, identical timestamps, then page the timeline backwards
        inbound(client, f"wamid.SYNINBOX07T{n}", sender=senders[0], minutes_ago=1)
    drain(app)
    target = next(t for t in threads(client).json()["items"] if t["party"]["address"].endswith("600"))
    newest = detail(client, target["id"], limit=4)
    older = detail(client, target["id"], limit=4, before=newest["before_cursor"])
    ids = [e["id"] for e in older["entries"] + newest["entries"]]
    assert len(ids) == 6 and len(set(ids)) == 6 and older["before_cursor"] is None
    review = {"through_seq": newest["thread"]["last_inbound_seq"]}
    assert client.post(f"{API}/threads/{target['id']}/review", json=review,
                       headers=mutation_headers(operator)).json()["changed"]  # fmt: skip
    inbound(client, "wamid.SYNINBOX07LATE", sender=senders[0], minutes_ago=60)  # backdated, arrives late
    drain(app)
    late = detail(client, target["id"], limit=100)
    assert late["thread"]["unread"] == 1 and late["entries"][0]["id"] != ids[0]  # placed by provider time, unread
    assert threads(client, cursor="not-a-cursor").status_code == 422
    assert threads(client, limit=500).status_code == 422
    assert client.get(f"{API}/threads/{target['id']}", params={"limit": 101}).status_code == 422


# --- INBOX-09 ------------------------------------------------------------------------------------------------------


def test_inbox_09_mark_reviewed_is_local_audited_idempotent_and_race_safe(
    app: FastAPI, client: TestClient, org: Org, operator: str, no_egress: list[str]
) -> None:
    inbound(client, "wamid.SYNINBOX0901")
    inbound(client, "wamid.SYNINBOX0902", minutes_ago=1)
    drain(app)
    thread = only_thread(client)
    url = f"{API}/threads/{thread['id']}/review"
    statuses: list[Any] = []
    barrier = threading.Barrier(2)

    def race() -> None:
        local = TestClient(app, raise_server_exceptions=False)
        csrf = logged_in(local, "operator@r.example")
        barrier.wait(timeout=10)
        statuses.append(local.post(url, json={"through_seq": thread["last_inbound_seq"]},
                                   headers=mutation_headers(csrf)).json())  # fmt: skip

    racers = [threading.Thread(target=race) for _ in range(2)]
    for t in racers:
        t.start()
    for t in racers:
        t.join(timeout=30)
    assert sorted(s["changed"] for s in statuses) == [False, True]
    again = client.post(url, json={"through_seq": 1}, headers=mutation_headers(operator)).json()
    assert again["changed"] is False and again["reviewed_through_seq"] == thread["last_inbound_seq"]
    beyond = client.post(url, json={"through_seq": 10**12}, headers=mutation_headers(operator)).json()
    assert beyond["changed"] is False  # clamped to what exists
    assert (
        client.post(url, json={"through_seq": 1, "send": True}, headers=mutation_headers(operator)).status_code == 422
    )
    with db(app) as session:
        audits = session.scalar(text("SELECT count(*) FROM action_audits WHERE action_type = 'inbox.thread_reviewed'"))
    assert audits == 1
    assert only_thread(client)["unread"] == 0
    inbound(client, "wamid.SYNINBOX0903", minutes_ago=0.5)
    drain(app)
    assert only_thread(client)["unread"] == 1
    assert no_egress == []


# --- INBOX-10 (API part; the browser part is e2e/inbox.spec.ts) ----------------------------------------------------


def test_inbox_10_no_reply_send_or_enrollment_surface_exists(app: FastAPI, client: TestClient, org: Org) -> None:
    from fastapi.routing import iter_route_contexts  # noqa: PLC0415

    from app.jobs import registry  # noqa: PLC0415

    paths = {(m, str(c.path)) for c in iter_route_contexts(app.routes) for m in (c.methods or ())}
    inbox_routes = sorted(p for p in paths if p[1].startswith(API))
    assert inbox_routes == [
        ("GET", f"{API}/threads"), ("GET", f"{API}/threads/{{thread_id}}"), ("POST", f"{API}/intent/backfill"),
        ("POST", f"{API}/messages/{{message_id}}/intent-review"), ("POST", f"{API}/rebuild"),
        ("POST", f"{API}/threads/{{thread_id}}/review"),  # P6.1 adds two local, non-sending routes
    ]  # fmt: skip
    assert not [t for t, _v in registry.REGISTRY if any(w in t for w in ("send", "reply", "dispatch"))]
    assert PHONE  # the bound test phone; the inbox has no route that takes a number
