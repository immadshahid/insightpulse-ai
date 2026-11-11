"""Background jobs for AI text (so screens never wait on the LLM)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.client import LLMError, get_llm
from app.ai.narratives import write_narratives, write_summary
from app.core import datasets as svc
from app.core.jobs import JobError, task
from app.deps import get_storage
from app.insights.dashboard import PERIOD_LABEL, kpi_cards, split_period
from app.models import Dataset, Job


def _dataset(db: Session, job: Job) -> Dataset:
    dataset = db.get(Dataset, job.dataset_id)
    if dataset is None or dataset.status != "ready":
        raise JobError("The dataset is not ready.")
    return dataset


@task("ai_narratives")
def narratives_task(db: Session, job: Job) -> dict[str, Any]:
    """2-3 sentence narrative per insight, written only from that insight's JSON."""
    dataset = _dataset(db, job)
    insights = svc.dataset_insights(get_storage(), dataset)
    try:
        narratives = write_narratives(get_llm(), insights)
    except LLMError as exc:
        raise JobError(str(exc)) from exc
    return {"narratives": narratives, "model": get_llm().model}


@task("ai_summary")
def summary_task(db: Session, job: Job) -> dict[str, Any]:
    """Dashboard summary for one period, from KPI cards + top insights."""
    dataset = _dataset(db, job)
    storage = get_storage()
    df = svc.load_clean(storage, dataset)
    period = job.params["period"]
    cur, prev, window = split_period(df, period)
    currency = svc.context_for(dataset, df).currency
    cards = [
        c.model_dump() for c in kpi_cards(cur, prev, currency, comparable=window.previous_complete)
    ]
    insights = [i for i in svc.dataset_insights(storage, dataset) if i.kind != "kpi_summary"]
    text = write_summary(get_llm(), PERIOD_LABEL[period], cards, insights, currency)
    if text is None:
        raise JobError("The AI summary could not be verified against the numbers.")
    return {"text": text, "model": get_llm().model}
