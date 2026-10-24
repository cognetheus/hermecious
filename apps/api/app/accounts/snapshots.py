"""Producer for `account.audit_snapshot` jobs (P1.5): domain audit + job + outbox in one transaction.

Does not commit: the caller's commit makes all three durable together.
"""

import uuid

from sqlalchemy.orm import Session

from app.accounts import management, service
from app.auth.dependencies import Capability
from app.auth.service import Actor
from app.core.clock import Clock
from app.jobs import service as jobs
from app.jobs.service import JobReceipt


def request_account_snapshot(
    db: Session, *, actor: Actor, clock: Clock, environment: str, account_id: uuid.UUID, idempotency_key: str
) -> JobReceipt:
    service._require(actor, Capability.MUTATE)
    account = service._account(db, actor, account_id)  # scoped: other organizations -> 404
    receipt = jobs.enqueue_job(
        db,
        organization_id=actor.organization_id,
        environment=environment,
        job_type="account.audit_snapshot",
        schema_version=1,
        payload={"account_id": str(account.id)},
        idempotency_key=idempotency_key,
        clock=clock,
    )
    if receipt.created:  # an exact replay records nothing new
        management._audit(db, actor, clock, "account.snapshot_requested", account.id, {"job_id": str(receipt.job_id)})
    return receipt
