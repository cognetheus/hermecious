"""Correlation across HTTP and worker jobs.

`enqueue` stamps the caller's request ID into the job's meta. The worker binds
that ID (validated, or a fresh `job_` ID) for exactly the duration of one job,
so log lines from a job carry the originating request's ID and nothing leaks
into the next job.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from rq import Queue
from rq.job import Job

from app.core.request_context import accept_request_id, bound_request_id, current_request_id, new_request_id

TRACE_META_KEY = "trace_id"

logger = logging.getLogger("app.worker")


def enqueue(queue: Queue, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
    trace_id = current_request_id() or new_request_id("job")
    return queue.enqueue(func, *args, meta={TRACE_META_KEY: trace_id}, **kwargs)


def job_trace_id(job: Job) -> str:
    candidate = job.meta.get(TRACE_META_KEY)
    return accept_request_id(candidate if isinstance(candidate, str) else None, prefix="job")


class TracingMixin:
    """Mix into an RQ Worker class ahead of the Worker base."""

    def perform_job(self, job: Job, queue: Queue) -> bool:
        with bound_request_id(job_trace_id(job)):
            started = time.perf_counter()
            context: dict[str, Any] = {"job_id": job.id, "job_type": job.func_name, "queue": queue.name}
            logger.info("job.started", extra={"context": context})
            succeeded: bool = super().perform_job(job, queue)  # type: ignore[misc]
            context["status"] = "succeeded" if succeeded else "failed"
            context["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            logger.log(logging.INFO if succeeded else logging.WARNING, "job.finished", extra={"context": context})
            return succeeded
