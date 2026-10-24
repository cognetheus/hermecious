"""Worker process (ADR-011): the Postgres-authoritative job runner, and its container health check.

PostgreSQL holds all job and outbox state. Redis, when configured, only
carries wake-up notifications; if it is down the runner keeps polling the
database, so the health check deliberately does not depend on Redis.
"""

import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg
from redis import Redis

from app.core.logging import configure_logging
from app.core.settings import SettingsError, load_settings
from app.jobs.runner import JobRunner, NoSink, NotificationSink, RedisSink
from app.persistence.db import make_engine, make_session_factory

# Container-local; the worker image has a single unprivileged user.
HEARTBEAT_FILE = Path("/tmp/hermecious-worker-heartbeat")  # noqa: S108
MAX_HEARTBEAT_AGE_SECONDS = 60
HEALTHCHECK_TIMEOUT_SECONDS = 2

logger = logging.getLogger("app.worker")


def write_heartbeat() -> None:
    HEARTBEAT_FILE.write_text(str(time.time()))


def heartbeat_is_fresh(now: float) -> bool:
    try:
        return now - float(HEARTBEAT_FILE.read_text()) <= MAX_HEARTBEAT_AGE_SECONDS
    except (OSError, ValueError):
        return False


def run() -> int:
    HEARTBEAT_FILE.unlink(missing_ok=True)  # a previous process's heartbeat must not vouch for this one
    try:
        settings = load_settings()
    except SettingsError as exc:
        configure_logging("worker", "unknown")
        logger.critical("config.invalid", extra={"context": {"settings": exc.names}})
        return 1
    configure_logging("worker", settings.environment, settings.log_level)
    factory = make_session_factory(make_engine(str(settings.database_url)))
    wake: Redis | None = None
    sink: NotificationSink = NoSink()
    if settings.job_notify == "redis":
        wake = Redis.from_url(str(settings.redis_url), socket_connect_timeout=2, socket_timeout=10)
        sink = RedisSink(wake)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    runner = JobRunner(
        factory,
        worker_id=f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}",
        environment=settings.environment,
        sink=sink,
        wake_client=wake,
        heartbeat=write_heartbeat,
    )
    runner.run_forever(stop)
    return 0


def healthcheck() -> int:
    """Healthy only if the runner loop is alive AND PostgreSQL (the queue authority) is reachable."""
    if not heartbeat_is_fresh(time.time()):
        print("unhealthy: no recent runner heartbeat")
        return 1
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"unhealthy: {exc}")
        return 1
    try:
        with psycopg.connect(str(settings.database_url), connect_timeout=HEALTHCHECK_TIMEOUT_SECONDS) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        print(f"unhealthy: queue database unreachable ({type(exc).__name__})")
        return 1
    print("healthy")
    return 0


if __name__ == "__main__":
    sys.exit(run())
