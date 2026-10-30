"""Meta webhook endpoints (P5.2, ADR-027). Public by design (Meta has no session); authenticated by HMAC.

- `GET  /api/v1/integrations/whatsapp/webhook`: subscription challenge (constant-time verify-token check).
- `POST /api/v1/integrations/whatsapp/webhook`: raw body capped, `X-Hub-Signature-256` verified before parsing,
  stored durably, then 200. Storage failure → 503 (Meta retries). Nothing here replies or sends.

Request logs record the path only (never the query string, so the verify token is not logged) and never a body.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import AppClock, AppSettings
from app.core.errors import DependencyUnavailable
from app.core.request_context import current_request_id
from app.whatsapp import inbox, webhook

router = APIRouter(prefix="/api/v1/integrations/whatsapp", tags=["whatsapp-webhook"])
logger = logging.getLogger("app.whatsapp")
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/webhook")
def verify(request: Request, settings: AppSettings) -> Response:
    token = settings.whatsapp_verify_token
    params = request.query_params
    if token is not None and webhook.valid_challenge(
        params.get("hub.mode"), params.get("hub.verify_token"), params.get("hub.challenge"), token.get_secret_value()
    ):
        return PlainTextResponse(params["hub.challenge"], headers=NO_STORE)
    return Response(status_code=403, headers=NO_STORE)  # never echoes the token or an unexpected challenge


async def _bounded_body(request: Request) -> bytes | None:
    """The exact raw bytes, or None once they exceed the cap (read no further)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > webhook.MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _refuse(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=NO_STORE)


@router.post("/webhook")
async def receive(request: Request, settings: AppSettings, clock: AppClock) -> Response:
    secret = settings.whatsapp_app_secret
    if secret is None:
        return _refuse(503, "webhook_not_configured")  # fail closed: nothing can be verified
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        return _refuse(415, "payload_invalid")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > webhook.MAX_BODY_BYTES:
        return _refuse(413, "payload_invalid")
    raw = await _bounded_body(request)
    if raw is None:
        return _refuse(413, "payload_invalid")
    if not webhook.valid_signature(secret.get_secret_value(), raw, request.headers.get("x-hub-signature-256")):
        logger.warning("whatsapp.webhook_signature_rejected")
        return _refuse(401, "webhook_signature")  # nothing from a forged body is stored
    factory = request.app.state.session_factory
    request_id = current_request_id()

    def store() -> dict[str, int]:
        with factory() as db:
            return inbox.receive(db, settings=settings, now=clock.now(), raw=raw, request_id=request_id)

    try:
        counts = await run_in_threadpool(store)
    except (OperationalError, DBAPIError, DependencyUnavailable):
        logger.warning("whatsapp.webhook_storage_unavailable")
        return _refuse(503, "storage_unavailable")  # no 2xx before a durable commit: Meta retries
    return JSONResponse({"status": "received", "accepted": counts["accepted"]}, headers=NO_STORE)
