"""Background worker.

The API writes a WorkflowRun row (status=queued) inside its transaction and, after commit, enqueues the
run id on Redis (RQ). The worker executes it with retries. If Redis is unavailable at enqueue time, the
run stays queued in Postgres and the sweeper below picks it up, so Postgres stays the source of truth
and Redis is only a delivery mechanism.

Run with:  python -m gtmos.worker
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import timedelta

from gtmos.config import get_settings

log = logging.getLogger("gtmos.worker")
QUEUE_NAME = "gtmos-workflows"


def _queue():  # type: ignore[no-untyped-def]
    from redis import Redis
    from rq import Queue

    url = get_settings().redis_url
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    return Queue(QUEUE_NAME, connection=Redis.from_url(url))


def enqueue_run(run_id: str) -> None:
    _queue().enqueue(execute_run_job, run_id, job_id=f"run-{run_id}", job_timeout=600, result_ttl=3600)


def execute_run_job(run_id: str) -> str:
    from gtmos.db import session_scope
    from gtmos.services.common import set_correlation_id
    from gtmos.services.workflow_engine import execute_run

    with session_scope() as db:
        from gtmos.models import WorkflowRun

        run = db.get(WorkflowRun, uuid.UUID(run_id))
        if run is not None:
            set_correlation_id(run.correlation_id)
        result = execute_run(db, uuid.UUID(run_id), sleep=time.sleep)
        return result.status


def sweep_stale_queued(max_age: timedelta = timedelta(minutes=2)) -> int:
    """Re-enqueue runs stuck in `queued` (e.g. Redis was down when they were created)."""
    from sqlalchemy import select

    from gtmos.db import session_scope
    from gtmos.models import WorkflowRun
    from gtmos.services.common import utcnow

    with session_scope() as db:
        stale = list(
            db.scalars(
                select(WorkflowRun.id)
                .where(WorkflowRun.status == "queued", WorkflowRun.created_at < utcnow() - max_age)
                .limit(100)
            )
        )
    for rid in stale:
        try:
            enqueue_run(str(rid))
        except Exception:
            log.exception("sweeper could not enqueue %s", rid)
    return len(stale)


def _sweeper_loop(interval: float = 60.0) -> None:
    while True:
        try:
            n = sweep_stale_queued()
            if n:
                log.info("sweeper re-enqueued %d stale runs", n)
        except Exception:
            log.exception("sweeper iteration failed")
        time.sleep(interval)


def main() -> None:
    from redis import Redis
    from rq import Worker

    logging.basicConfig(level=get_settings().log_level)
    threading.Thread(target=_sweeper_loop, daemon=True).start()
    conn = Redis.from_url(get_settings().redis_url or "redis://localhost:6379/0")
    Worker([QUEUE_NAME], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
