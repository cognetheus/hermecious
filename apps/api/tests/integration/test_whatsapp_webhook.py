"""P5.2 acceptance WAHOOK-01..10 (API + Postgres + the P1.5 runner). Signed with a test secret over exact bytes.

Synthetic, zero-filled numbers only. No Graph call is possible from any code path exercised here.
"""

import hashlib
import hmac
import json
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.contacts.models import Contact, SuppressionEntry
from app.jobs.models import Job
from app.whatsapp import inbox, service
from app.whatsapp.models import (
    ProviderEventItem,
    ProviderInboundMessage,
    ProviderMessageStatus,
    ProviderServiceWindow,
    ProviderStatusObservation,
    ProviderWebhookEnvelope,
)
from tests.conftest import FIXED_NOW
from tests.integration.auth_helpers import db, logged_in, mutation_headers
from tests.integration.test_campaigns import plain_account
from tests.integration.test_eligibility import add_contact
from tests.integration.test_research import Org, worker

pytestmark = pytest.mark.usefixtures("app")
URL = "/api/v1/integrations/whatsapp/webhook"
WABA, PHONE = "100000000000001", "200000000000002"
SECRET = "synthetic-app-secret-for-tests-0123456789"
VERIFY = "synthetic-verify-token-0123456789"
KNOWN, STRANGER = "920000000101", "920000000555"


@pytest.fixture
def org(app: FastAPI) -> Org:
    app.state.settings = app.state.settings.model_copy(
        update={
            "whatsapp_mode": "contract_test", "whatsapp_waba_id": WABA, "whatsapp_phone_number_id": PHONE,
            "whatsapp_app_secret": SecretStr(SECRET), "whatsapp_verify_token": SecretStr(VERIFY),
        }
    )  # fmt: skip
    org = Org(app)
    with db(app) as session:
        service.bind_connection(session, actor=org.actor, clock=app.state.clock, settings=app.state.settings)
    return org


@pytest.fixture
def operator(client: TestClient, org: Org) -> str:
    return logged_in(client, "operator@r.example")


def ts(minutes_ago: float) -> str:
    return str(int((FIXED_NOW - timedelta(minutes=minutes_ago)).timestamp()))


def message(
    wamid: str, sender: str = KNOWN, text: str | None = "hello", minutes_ago: float = 2, kind: str = "text"
) -> dict[str, Any]:
    body: dict[str, Any] = {"from": sender, "id": wamid, "timestamp": ts(minutes_ago), "type": kind}
    if kind == "text":
        body["text"] = {"body": text}
    return body


def status(wamid: str, state: str, minutes_ago: float, code: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"id": wamid, "status": state, "timestamp": ts(minutes_ago), "recipient_id": KNOWN}
    if code is not None:
        body["errors"] = [{"code": code, "title": "synthetic"}]
    return body


def change(
    messages: tuple[dict[str, Any], ...] = (), statuses: tuple[dict[str, Any], ...] = (), phone: str = PHONE,
    field: str = "messages",
) -> dict[str, Any]:  # fmt: skip
    return {
        "field": field,
        "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": phone},
            "contacts": [{"profile": {"name": "Synthetic Sender"}, "wa_id": KNOWN}],
            "messages": list(messages),
            "statuses": list(statuses),
        },
    }


def envelope(*changes: dict[str, Any], waba: str = WABA) -> dict[str, Any]:
    return {"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": list(changes)}]}


def sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def post(client: TestClient, body: dict[str, Any] | bytes, signature: str | None = None, **headers: str) -> Any:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(
        URL,
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature or sign(raw), **headers},
    )


def count(app: FastAPI, model: type[Any], **where: Any) -> int:
    with db(app) as session:
        query = select(func.count()).select_from(model)
        for name, value in where.items():
            query = query.where(getattr(model, name) == value)
        return int(session.scalar(query) or 0)


def drain(app: FastAPI) -> None:
    while [o for o in worker(app).run_once() if o.status == "succeeded"]:
        pass


def evaluate(client: TestClient, csrf: str, contact: str, purpose: str) -> dict[str, Any]:
    body = {"contact_id": contact, "purpose": purpose}
    result: dict[str, Any] = client.post(
        "/api/v1/channel-eligibility/evaluate", json=body, headers=mutation_headers(csrf)
    ).json()
    return result


def known_contact(app: FastAPI, client: TestClient, org: Org, operator: str) -> str:
    account = plain_account(app, org, "Inbound School (Synthetic)")
    created = add_contact(client, operator, account, "+92 000 0000101")
    assert created.status_code == 201, created.text
    contact: str = created.json()["id"]
    return contact


# --- WAHOOK-01 -----------------------------------------------------------------------------------------------------


def test_wahook_01_get_challenge_only_for_the_verify_token(
    app: FastAPI, client: TestClient, org: Org, json_logs: Any
) -> None:
    ok = client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"})
    assert (ok.status_code, ok.text, ok.headers["content-type"].split(";")[0]) == (200, "1158201444", "text/plain")
    for params in (
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "<script>"},
        {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "x" * 129},
        {"hub.mode": "subscribe", "hub.challenge": "1"},
    ):
        refused = client.get(URL, params=params)
        assert refused.status_code == 403 and refused.text == "", params
    app.state.settings = app.state.settings.model_copy(update={"whatsapp_verify_token": None})
    assert (
        client.get(URL, params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"}).status_code
        == 403
    )
    assert VERIFY not in json.dumps(json_logs(), default=str)  # request logs record the path, not the query


# --- WAHOOK-02 -----------------------------------------------------------------------------------------------------


def test_wahook_02_only_an_exactly_signed_body_is_stored(app: FastAPI, client: TestClient, org: Org) -> None:
    raw = json.dumps(envelope(change(messages=(message("wamid.SYN0000000001"),)))).encode()
    accepted = post(client, raw)
    assert accepted.status_code == 200 and accepted.json()["accepted"] == 1
    tampered = raw.replace(b"hello", b"hellp")
    assert post(client, tampered, signature=sign(raw)).status_code == 401  # one changed byte
    assert post(client, raw, signature=sign(raw, "another-secret-0123456789")).status_code == 401
    assert post(client, raw, signature="sha1=" + "0" * 40).status_code == 401
    assert post(client, raw, signature="sha256=nothex").status_code == 401
    unsigned = client.post(URL, content=raw, headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 401
    assert (count(app, ProviderWebhookEnvelope), count(app, ProviderEventItem)) == (1, 1)  # nothing forged stored
    app.state.settings = app.state.settings.model_copy(update={"whatsapp_app_secret": None})
    assert post(client, raw).status_code == 503  # fail closed when nothing can be verified


# --- WAHOOK-03 -----------------------------------------------------------------------------------------------------


def test_wahook_03_mixed_batch_items_land_on_the_right_connection(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    known_contact(app, client, org, operator)
    foreign = change(messages=(message("wamid.SYN0000000011"),), phone="200000000999")
    body = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": WABA, "changes": [
                change(messages=(message("wamid.SYN0000000010"),), statuses=(status("wamid.SYNOUT000001", "sent", 3),)),
                change(statuses=(status("wamid.SYNOUT000001", "delivered", 2),)),
            ]},
            {"id": "100000000999", "changes": [foreign]},
        ],
    }  # fmt: skip
    received = post(client, body)
    assert received.status_code == 200 and received.json()["accepted"] == 3
    with db(app) as session:
        envelope_row = session.scalar(select(ProviderWebhookEnvelope))
        assert envelope_row is not None and envelope_row.counts_json["unmapped"] == 1  # never attached anywhere
        items = list(session.scalars(select(ProviderEventItem)))
    assert {i.organization_id for i in items} == {org.id} and len(items) == 3
    drain(app)
    assert count(app, ProviderInboundMessage) == 1 and count(app, ProviderStatusObservation) == 2
    with db(app) as session:
        projection = session.scalar(select(ProviderMessageStatus))
    assert projection is not None and (projection.status, projection.observations) == ("delivered", 2)


# --- WAHOOK-04 -----------------------------------------------------------------------------------------------------


def test_wahook_04_redelivery_and_overlap_yield_one_logical_message(app: FastAPI, client: TestClient, org: Org) -> None:
    first = envelope(change(messages=(message("wamid.SYN0000000020", sender=STRANGER),)))
    assert post(client, first).json()["accepted"] == 1
    assert post(client, first).json()["accepted"] == 0  # exact retry
    overlap = envelope(change(messages=(message("wamid.SYN0000000020", sender=STRANGER),
                                        message("wamid.SYN0000000021", sender=STRANGER))))  # fmt: skip
    assert post(client, overlap).json()["accepted"] == 1
    drain(app)
    drain(app)
    assert count(app, ProviderInboundMessage) == 2 and count(app, ProviderEventItem) == 2
    assert count(app, ProviderWebhookEnvelope) == 3  # every delivery is audited, items are not duplicated


# --- WAHOOK-05 -----------------------------------------------------------------------------------------------------


def test_wahook_05_no_2xx_before_a_durable_commit(
    app: FastAPI, client: TestClient, org: Org, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = envelope(change(messages=(message("wamid.SYN0000000030", sender=STRANGER),)))
    real_receive = inbox.receive

    def database_down(*_a: Any, **_k: Any) -> Any:
        raise OperationalError("INSERT", {}, Exception("connection refused"))

    monkeypatch.setattr(inbox, "receive", database_down)
    refused = post(client, body)
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "storage_unavailable"
    assert count(app, ProviderEventItem) == 0
    monkeypatch.setattr(inbox, "receive", real_receive)
    assert post(client, body).status_code == 200  # Meta's retry is accepted once storage is back
    assert count(app, ProviderEventItem) == 1


# --- WAHOOK-06 -----------------------------------------------------------------------------------------------------


def test_wahook_06_worker_crash_and_racing_workers_project_exactly_once(
    app: FastAPI, client: TestClient, org: Org, monkeypatch: pytest.MonkeyPatch
) -> None:
    for n in range(6):
        post(client, envelope(change(messages=(message(f"wamid.SYN00000004{n}", sender=STRANGER),))))
    real_inbound = inbox._inbound
    crashed: list[bool] = []

    def crash_once(*args: Any) -> None:
        if not crashed:
            crashed.append(True)
            from app.core.errors import DependencyUnavailable  # noqa: PLC0415

            raise DependencyUnavailable()  # dies before commit: the item must stay pending
        real_inbound(*args)

    monkeypatch.setattr(inbox, "_inbound", crash_once)
    first = worker(app).run_once()
    assert "retry_wait" in [o.status for o in first]  # the crashed attempt is retried, nothing half-applied
    assert count(app, ProviderInboundMessage) == count(app, ProviderEventItem, processing_status="processed")
    monkeypatch.setattr(inbox, "_inbound", real_inbound)
    app.state.clock.advance(timedelta(minutes=5))
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def race(name: str) -> None:
        barrier.wait(timeout=10)
        outcomes.extend(o.status for o in worker(app, name).run_once())

    threads = [threading.Thread(target=race, args=(f"worker-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    drain(app)
    assert count(app, ProviderInboundMessage) == 6 and count(app, ProviderEventItem, processing_status="processed") == 6


# --- WAHOOK-07 -----------------------------------------------------------------------------------------------------


def test_wahook_07_out_of_order_and_conflicting_statuses_never_falsely_regress(
    app: FastAPI, client: TestClient, org: Org
) -> None:
    wamid, other = "wamid.SYNOUT000070", "wamid.SYNOUT000071"
    for state, minutes in (("read", 1), ("sent", 3), ("delivered", 2)):  # arrival order differs from provider order
        post(client, envelope(change(statuses=(status(wamid, state, minutes),))))
        drain(app)
    post(client, envelope(change(statuses=(status(wamid, "failed", 0.5, code=131026),))))
    post(client, envelope(change(statuses=(status(other, "failed", 4, code=131049),))))
    post(client, envelope(change(statuses=(status(other, "delivered", 3),))))
    drain(app)
    with db(app) as session:
        rows = {r.provider_message_id: r for r in session.scalars(select(ProviderMessageStatus))}
        observed = list(session.scalars(select(ProviderStatusObservation.status).where(
            ProviderStatusObservation.provider_message_id == wamid)))  # fmt: skip
    assert sorted(observed) == ["delivered", "failed", "read", "sent"]  # every genuine observation is kept
    assert (rows[wamid].status, rows[wamid].conflict, rows[wamid].conflict_reason) == (
        "read", True, "failed_after_delivered",
    )  # fmt: skip
    assert (rows[other].status, rows[other].conflict_reason) == ("delivered", "success_after_failed")


# --- WAHOOK-08 -----------------------------------------------------------------------------------------------------


def test_wahook_08_wrong_binding_shape_size_and_type_are_contained(app: FastAPI, client: TestClient, org: Org) -> None:
    Org(app, "Other Org", "o")
    assert (
        post(client, envelope(change(messages=(message("wamid.SYN0000000080"),)), waba="100000000000999")).json()[
            "accepted"
        ]
        == 0
    )  # right phone, wrong WABA: unmapped
    assert (
        post(client, envelope(change(messages=(message("wamid.SYN0000000081"),), phone="200000000000999"))).json()[
            "accepted"
        ]
        == 0
    )  # unconfigured phone
    assert post(client, {"object": "page", "entry": []}).status_code == 200  # signed but foreign: quarantined
    assert post(client, b"[1, 2").status_code == 200
    assert post(client, b"x" * (256 * 1024 + 1)).status_code == 413
    plain = {"Content-Type": "text/plain", "X-Hub-Signature-256": sign(b"{}")}
    assert client.post(URL, content=b"{}", headers=plain).status_code == 415
    sticker_change = change(messages=(message("wamid.SYN0000000082", kind="sticker"),))
    unsupported = post(client, envelope(change(field="account_update"), sticker_change))
    assert unsupported.status_code == 200
    drain(app)
    with db(app) as session:
        quarantined = list(session.scalars(select(ProviderWebhookEnvelope.quarantine_reason).where(
            ProviderWebhookEnvelope.parse_status == "quarantined")))  # fmt: skip
        sticker = session.scalar(select(ProviderInboundMessage))
        orgs = set(session.scalars(select(ProviderEventItem.organization_id)))
    assert {"unmapped", "object_unsupported", "payload_invalid"} <= set(quarantined)
    assert count(app, ProviderEventItem, processing_status="quarantined") == 1  # the account_update change
    assert sticker is not None and sticker.kind == "unsupported"
    assert orgs == {org.id}  # nothing ever attached to the other organization


# --- WAHOOK-09 -----------------------------------------------------------------------------------------------------


def test_wahook_09_verified_inbound_sets_only_service_window_provenance(
    app: FastAPI, client: TestClient, org: Org, operator: str
) -> None:
    contact = known_contact(app, client, org, operator)
    contacts_before = count(app, Contact)
    first = (
        message("wamid.SYN0000000090", minutes_ago=30),
        message("wamid.SYN0000000091", sender=STRANGER, minutes_ago=5),
    )
    post(client, envelope(change(messages=first)))
    post(client, envelope(change(messages=(message("wamid.SYN0000000092", minutes_ago=60),))))  # older, later
    future = post(client, envelope(change(messages=(message("wamid.SYN0000000093", minutes_ago=-60),))))
    assert future.json()["accepted"] == 0  # a future timestamp never extends a window
    drain(app)
    with db(app) as session:
        window = session.scalar(select(ProviderServiceWindow))
        stranger = session.scalar(select(ProviderInboundMessage).where(
            ProviderInboundMessage.provider_message_id == "wamid.SYN0000000091"))  # fmt: skip
    assert window is not None and window.last_verified_inbound_at == FIXED_NOW - timedelta(
        minutes=30
    )  # max, not latest
    assert stranger is not None and (stranger.assignment, stranger.contact_id) == ("unassigned", None)
    assert count(app, Contact) == contacts_before  # an unknown sender never becomes a contact or an account
    reply = evaluate(client, operator, contact, "service_reply")
    assert reply["decision"] == "allow_for_simulation" and reply["live_send_authorized"] is False
    marketing = evaluate(client, operator, contact, "marketing")
    assert "no_opt_in_permission" in [r["code"] for r in marketing["reasons"]]  # inbound is never consent
    stops = (message("wamid.SYN0000000094", text="STOP", minutes_ago=1),
             message("wamid.SYN0000000095", sender=STRANGER, text="unsubscribe"))  # fmt: skip
    post(client, envelope(change(messages=stops)))
    drain(app)
    with db(app) as session:
        suppressions = list(session.scalars(select(SuppressionEntry)))
    assert len(suppressions) == 2 and {s.reason for s in suppressions} == {"opt_out"}
    assert {str(s.contact_id) if s.contact_id else None for s in suppressions} == {contact, None}
    stopped = evaluate(client, operator, contact, "service_reply")
    assert stopped["decision"] == "deny" and "suppressed" in [r["code"] for r in stopped["reasons"]]


# --- WAHOOK-10 -----------------------------------------------------------------------------------------------------


def test_wahook_10_constant_time_safe_logs_bounded_latency_and_zero_outbound(
    app: FastAPI, client: TestClient, org: Org, json_logs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.egress import https_client  # noqa: PLC0415

    def no_egress(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the webhook path must never build an egress client")

    monkeypatch.setattr(https_client.PinnedHttpsClient, "__init__", no_egress)
    body = envelope(change(messages=(message("wamid.SYN0000000100", sender=STRANGER, text="secret school detail"),)))
    started = time.perf_counter()
    assert post(client, body).status_code == 200
    assert time.perf_counter() - started < 2.0  # the 200 waits only for the durable commit, not for processing
    drain(app)
    logs = json.dumps(json_logs(), default=str)
    for secret in (SECRET, VERIFY, "secret school detail", STRANGER, "+" + STRANGER):
        assert secret not in logs, secret
    source = (Path(inbox.__file__).parent / "webhook.py").read_text()
    assert "hmac.compare_digest" in source and source.count("compare_digest") >= 2
    with db(app) as session:
        job_types = set(session.scalars(select(Job.job_type)))
        stored = json.dumps([i.normalized_json for i in session.scalars(select(ProviderEventItem))])
    assert job_types == {"provider_inbox.process"}  # the only job: inbound processing, never a send
    assert "secret school detail" not in stored and STRANGER not in stored  # no body text, no raw number
