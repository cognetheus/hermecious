"""A7: request IDs propagate into worker jobs and never leak between jobs (real Redis)."""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from rq.job import Job

from app.core.request_context import bound_request_id, current_request_id
from app.core.settings import Settings
from app.workers.tracing import TRACE_META_KEY, TracingMixin, enqueue

Logs = Callable[[], list[dict[str, Any]]]


def record_trace(label: str) -> dict[str, str | None]:
    return {"label": label, "trace": current_request_id()}


def failing_job() -> None:
    raise RuntimeError("job failed with postgresql://u:job-secret-value@h/db")


class TracedSimpleWorker(TracingMixin, SimpleWorker):
    pass


@pytest.fixture
def queue(settings: Settings) -> Iterator[Queue]:
    connection = Redis.from_url(str(settings.redis_url))
    q = Queue(f"trace-test-{uuid.uuid4().hex[:8]}", connection=connection)
    yield q
    q.delete(delete_jobs=True)
    connection.close()


def outcome(job: Job) -> dict[str, str | None]:
    value = job.return_value()
    assert isinstance(value, dict)
    return value


def run_burst(queue: Queue) -> None:
    worker = TracedSimpleWorker([queue], connection=queue.connection, log_job_description=False)
    worker.work(burst=True)


def test_jobs_inherit_the_enqueuing_request_id_and_do_not_leak(queue: Queue, json_logs: Logs) -> None:
    with bound_request_id("req_origin_0000000000000001"):
        from_request = enqueue(queue, record_trace, "from-request")
    standalone = enqueue(queue, record_trace, "standalone")
    tampered = enqueue(queue, record_trace, "tampered")
    tampered.meta[TRACE_META_KEY] = 'bad"\nid'
    tampered.save_meta()  # type: ignore[no-untyped-call]  # rq leaves this unannotated

    run_burst(queue)

    results = {outcome(job)["label"]: outcome(job)["trace"] for job in (from_request, standalone, tampered)}
    assert results["from-request"] == "req_origin_0000000000000001"
    assert results["standalone"] is not None and results["standalone"].startswith("job_")
    assert results["tampered"] is not None and results["tampered"].startswith("job_")
    assert len(set(results.values())) == 3
    assert current_request_id() is None

    finished = [e for e in json_logs() if e["event"] == "job.finished"]
    assert [e["request_id"] for e in finished] == [results["from-request"], results["standalone"], results["tampered"]]
    assert all(e["context"]["status"] == "succeeded" for e in finished)


def test_failed_job_clears_context_and_scrubs_logs(queue: Queue, json_logs: Logs) -> None:
    with bound_request_id("req_failing_000000000000001"):
        job = enqueue(queue, failing_job)
    follow_up = enqueue(queue, record_trace, "after-failure")

    run_burst(queue)

    assert job.is_failed
    assert outcome(follow_up)["trace"] != "req_failing_000000000000001"
    assert current_request_id() is None
    logs = json_logs()
    [failed] = [e for e in logs if e["event"] == "job.finished" and e["context"]["status"] == "failed"]
    assert failed["request_id"] == "req_failing_000000000000001"
    assert "job-secret-value" not in json.dumps(logs)
