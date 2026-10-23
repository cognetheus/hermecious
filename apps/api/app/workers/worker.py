"""RQ worker runtime (ADR-009) and its container health check.

Each worker process registers under a unique name, which it records in
NAME_FILE so the health check can find this exact worker's heartbeat in
Redis. The check fails when Redis is unreachable or the heartbeat is stale,
so a healthy Redis cannot make a dead or hung worker look healthy.
"""

import socket
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from redis import Redis
from rq import Worker
from rq.utils import now

from app.core.settings import SettingsError, load_settings

QUEUES = ["default"]
# RQ refreshes the heartbeat at least every WORKER_TTL_SECONDS - 15 while idle.
WORKER_TTL_SECONDS = 30
MAX_HEARTBEAT_AGE = timedelta(seconds=WORKER_TTL_SECONDS)
NAME_FILE = Path("/tmp/hermecious-worker-name")
HEALTHCHECK_TIMEOUT_SECONDS = 2


def heartbeat_is_fresh(last_heartbeat: datetime | None, at: datetime) -> bool:
    return last_heartbeat is not None and at - last_heartbeat <= MAX_HEARTBEAT_AGE


def run() -> int:
    # Forget any previous process's name first, so its still-fresh heartbeat
    # cannot vouch for this process.
    NAME_FILE.unlink(missing_ok=True)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"hermecious-worker: refusing to start: {exc}", file=sys.stderr)
        return 1
    # A fresh suffix per process avoids RQ rejecting a restart while the
    # previous registration (same hostname) has not yet expired.
    name = f"hermecious-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    NAME_FILE.write_text(name)
    worker = Worker(QUEUES, connection=Redis.from_url(str(settings.redis_url)), name=name, worker_ttl=WORKER_TTL_SECONDS)
    worker.work()
    return 0


def healthcheck() -> int:
    try:
        name = NAME_FILE.read_text().strip()
    except OSError:
        print("unhealthy: worker has not registered")
        return 1
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"unhealthy: {exc}")
        return 1
    connection = Redis.from_url(
        str(settings.redis_url),
        socket_connect_timeout=HEALTHCHECK_TIMEOUT_SECONDS,
        socket_timeout=HEALTHCHECK_TIMEOUT_SECONDS,
    )
    try:
        worker = Worker.find_by_key(Worker.redis_worker_namespace_prefix + name, connection=connection)
    except Exception as exc:
        print(f"unhealthy: broker unreachable ({type(exc).__name__})")
        return 1
    if worker is None or not heartbeat_is_fresh(worker.last_heartbeat, now()):
        print("unhealthy: no fresh heartbeat")
        return 1
    print("healthy")
    return 0
