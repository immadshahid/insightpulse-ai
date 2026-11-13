"""GET /datasets/{id}/dashboard and GET /datasets/{id}/insights."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.ai.client import LLMClient, get_llm
from app.core import datasets as svc
from app.core.jobs import JobRunner, find_or_create_job
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_job_runner, get_storage, require_ready, require_sales
from app.insights.base import Category
from app.insights.dashboard import (
    Period,
    kpi_cards,
    kpi_sparklines,
    revenue_trend_chart,
    split_period,
    summary_text,
)
from app.models import Dataset
from app.schemas import AiSummary, DashboardOut, ForecastStatus, InsightsOut

router = APIRouter(prefix="/datasets", tags=["insights"])

# The Home chart reuses the Forecast screen's default request, so both share one job.
HOME_FORECAST = {"target": "revenue", "horizon_days": 90}
MIN_FORECAST_DAYS = 14


def home_forecast(
    db: Session, dataset: Dataset, history_days: int, runner: JobRunner
) -> tuple[ForecastStatus, dict | None]:
    """Start (once per data version) or read the revenue forecast for the Home chart."""
    if history_days < MIN_FORECAST_DAYS:
        return ForecastStatus(status="unavailable"), None
    job, created = find_or_create_job(db, dataset, "forecast", HOME_FORECAST)
    if created:
        runner.submit(job.id)
    if job.status == "succeeded" and job.result:
        return (
            ForecastStatus(
                status="ready",
                job_id=job.id,
                model=job.result.get("model"),
                accuracy_note=job.result.get("accuracy_note"),
            ),
            job.result,
        )
    state = "failed" if job.status == "failed" else "pending"
    return ForecastStatus(status=state, job_id=job.id), None


def ai_job(
    db: Session, dataset: Dataset, kind: str, params: dict, llm: LLMClient, runner: JobRunner
) -> tuple[str, dict | None]:
    """Start (once per data version) or read an AI text job: (status, result)."""
    if not llm.available:
        return "off", None
    job, created = find_or_create_job(db, dataset, kind, params)
    if created:
        runner.submit(job.id)
    if job.status == "succeeded":
        return "ready", job.result
    return ("failed" if job.status == "failed" else "pending"), None


@router.get("/{dataset_id}/dashboard", response_model=DashboardOut)
def get_dashboard(
    period: Period = Query("30d"),
    dataset: Dataset = Depends(require_sales),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    runner: JobRunner = Depends(get_job_runner),
    llm: LLMClient = Depends(get_llm),
) -> DashboardOut:
    """KPI cards (vs previous period), summary, top insights, chart URLs and forecast state.

    The first call for a dataset version starts a background revenue forecast (and, with
    AI on, an AI summary for the period); once finished, the trend chart includes the
    forecast and the summary switches from template text to the verified AI text.
    """
    df = svc.load_clean(storage, dataset)
    ctx = svc.context_for(dataset, df)
    cur, prev, window = split_period(df, period)
    cards = kpi_cards(cur, prev, ctx.currency, comparable=window.previous_complete)
    sparks = kpi_sparklines(cur, window, period)
    cards = [c.model_copy(update={"spark": sparks.get(c.key, [])}) for c in cards]
    insights = [i for i in svc.dataset_insights(storage, dataset) if i.kind != "kpi_summary"]
    top = insights[:3]
    history_days = (dataset.cleaning or {}).get("history_days", 0)
    forecast_state, forecast = home_forecast(db, dataset, history_days, runner)
    summary_status, summary = ai_job(db, dataset, "ai_summary", {"period": period}, llm, runner)
    if summary_status == "ready" and summary:
        ai_summary = AiSummary(text=summary["text"], source="llm", status="ready")
    else:
        ai_summary = AiSummary(
            text=summary_text(cards, period, top[0] if top else None), status=summary_status
        )
    out = DashboardOut(
        dataset_id=dataset.id,
        period=period,
        window=window,
        currency=ctx.currency,
        kpis=cards,
        ai_summary=ai_summary,
        top_insights=[svc.insight_out(db, dataset, i) for i in top],
        charts={
            "revenue_trend": svc.register_chart(
                db, dataset, revenue_trend_chart(df, cur, period, ctx.currency, forecast)
            )
        },
        forecast=forecast_state,
    )
    db.commit()
    return out


@router.get("/{dataset_id}/insights", response_model=InsightsOut)
def get_insights(
    category: Category | None = Query(None),
    limit: int = Query(10, ge=1, le=10),
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    runner: JobRunner = Depends(get_job_runner),
    llm: LLMClient = Depends(get_llm),
) -> InsightsOut:
    """Top insights by score, optionally filtered by category.

    With AI on, the first call starts a background job that writes a short narrative
    for each insight; later calls fill ``narrative`` (``narratives`` = 'ready').
    """
    items = [
        i
        for i in svc.dataset_insights(storage, dataset)
        if category is None or i.category == category
    ][:limit]
    state, result = ai_job(db, dataset, "ai_narratives", {}, llm, runner)
    texts = (result or {}).get("narratives", {})
    out = InsightsOut(
        dataset_id=dataset.id,
        items=[
            svc.insight_out(db, dataset, i.model_copy(update={"narrative": texts.get(i.id)}))
            for i in items
        ],
        narratives=state,
    )
    db.commit()
    return out
