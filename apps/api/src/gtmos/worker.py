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
from datetime import datetime, timedelta
from typing import Any

from gtmos.config import get_settings

log = logging.getLogger("gtmos.worker")
QUEUE_NAME = "gtmos-workflows"


def _queue() -> Any:
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


# A run that is still `running` long after any real execution would have finished belongs to a worker
# that died. Generous, because the bound must exceed the slowest legitimate run: re-enqueuing a run that
# is merely slow is safe (the executor's row lock makes the second worker a no-op) but pointless.
ABANDONED_AFTER = timedelta(minutes=30)


def stale_run_ids(
    db: Any,
    now: datetime,
    max_age: timedelta = timedelta(minutes=2),
    abandoned_after: timedelta = ABANDONED_AFTER,
    limit: int = 100,
) -> list[uuid.UUID]:
    """Runs no worker is going to pick up.

    Two ways that happens. A run stuck in `queued` was never enqueued at all — Redis was down when it
    was created. A run stuck in `running` was claimed by a worker that then died: nothing re-enqueues
    it, because the enqueue happened before the crash, so without this it sits half-executed forever.
    Both are safe to re-enqueue: `execute_run` skips completed steps and takes a row lock, so a run
    that is in fact still alive elsewhere is a no-op rather than a duplicate.

    Separate from the sweeping so the selection can be tested against a session, rather than only
    through a function that opens its own.
    """
    from sqlalchemy import or_, select

    from gtmos.models import WorkflowRun

    return list(
        db.scalars(
            select(WorkflowRun.id)
            .where(
                or_(
                    (WorkflowRun.status == "queued") & (WorkflowRun.created_at < now - max_age),
                    (WorkflowRun.status == "running") & (WorkflowRun.started_at < now - abandoned_after),
                )
            )
            .limit(limit)
        )
    )


def sweep_stale_queued(max_age: timedelta = timedelta(minutes=2), abandoned_after: timedelta = ABANDONED_AFTER) -> int:
    """Re-enqueue everything `stale_run_ids` finds."""
    from gtmos.db import session_scope
    from gtmos.services.common import utcnow

    with session_scope() as db:
        stale = stale_run_ids(db, utcnow(), max_age, abandoned_after)
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
