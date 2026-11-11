"""Background jobs behind a small interface.

A job row stores kind + params; a registered task function does the work given a DB
session and the job. :class:`BackgroundTasksRunner` runs it after the HTTP response
(FastAPI BackgroundTasks). Moving to Celery + Redis later means adding a runner whose
``submit`` sends ``execute_job(job_id)`` to a worker; tasks and endpoints stay the same.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Protocol

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.insights.base import jsonable
from app.models import Dataset, Job, utcnow

log = logging.getLogger(__name__)

TaskFn = Callable[[Session, Job], dict[str, Any]]
TASKS: dict[str, TaskFn] = {}
STALE_AFTER = timedelta(minutes=30)  # queued/running longer than this = lost (e.g. restart)


class JobError(Exception):
    """A task failure whose message is safe to show to the user."""


def task(name: str) -> Callable[[TaskFn], TaskFn]:
    """Register a task function under ``name``."""

    def register(fn: TaskFn) -> TaskFn:
        TASKS[name] = fn
        return fn

    return register


class JobRunner(Protocol):
    """Schedules a stored job for execution."""

    def submit(self, job_id: str) -> None: ...


class BackgroundTasksRunner:
    """Runs jobs in-process after the response is sent."""

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self.background_tasks = background_tasks

    def submit(self, job_id: str) -> None:
        """Queue ``execute_job`` to run after the response."""
        self.background_tasks.add_task(execute_job, job_id)


class InlineRunner:
    """Runs jobs immediately (scripts, debugging)."""

    def submit(self, job_id: str) -> None:
        """Execute right now in this thread."""
        execute_job(job_id)


def params_key(kind: str, dataset: Dataset, params: dict[str, Any]) -> str:
    """Stable key so identical requests on the same data version reuse one job."""
    blob = json.dumps(
        {"k": kind, "d": dataset.id, "v": dataset.version, "p": params}, sort_keys=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:40]


def find_or_create_job(
    db: Session, dataset: Dataset, kind: str, params: dict[str, Any]
) -> tuple[Job, bool]:
    """Return an existing live/succeeded job for the same request, or a new queued one."""
    key = params_key(kind, dataset, params)
    candidates = db.scalars(
        select(Job).where(Job.params_key == key).order_by(Job.created_at.desc())
    ).all()
    now = utcnow()
    for job in candidates:
        if job.status == "succeeded":
            return job, False
        created = (
            job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=now.tzinfo)
        )
        if job.status in ("queued", "running") and now - created < STALE_AFTER:
            return job, False
    job = Job(
        user_id=dataset.user_id,
        dataset_id=dataset.id,
        dataset_version=dataset.version,
        kind=kind,
        params=params,
        params_key=key,
        status="queued",
    )
    db.add(job)
    db.commit()
    return job, True


def latest_job(db: Session, dataset: Dataset, kind: str, params: dict[str, Any]) -> Job | None:
    """Most recent job for this exact request on the current data version."""
    key = params_key(kind, dataset, params)
    return db.scalars(
        select(Job).where(Job.params_key == key).order_by(Job.created_at.desc())
    ).first()


def execute_job(job_id: str) -> None:
    """Run a job in its own DB session and record the result or error."""
    import app.ai.tasks  # noqa: F401  (registers task functions)
    import app.ml.tasks  # noqa: F401

    db = get_sessionmaker()()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status, job.started_at = "running", utcnow()
        db.commit()
        try:
            fn = TASKS[job.kind]
            job.result = jsonable(fn(db, job))
            job.status = "succeeded"
        except JobError as exc:
            job.status, job.error = "failed", str(exc)
        except Exception:  # noqa: BLE001 - never leak internals to the client
            log.exception("Job %s (%s) failed", job_id, job.kind)
            job.status, job.error = "failed", "Something went wrong while running this job."
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()
