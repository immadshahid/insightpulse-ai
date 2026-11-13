"""Monthly PDF report: which months are available, and the PDF itself."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.client import LLMClient, get_llm
from app.api.ai import HOME_FORECAST, recommendations
from app.core import datasets as svc
from app.core.jobs import latest_job
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_storage, require_ready
from app.eda.predict import PredictError, predict_column
from app.insights.base import month_label
from app.ml.forecast import ForecastResult, forecast_chart_spec
from app.models import Dataset
from app.reports.data_pdf import render_data_pdf
from app.reports.monthly import ReportError, available_months, build_report, default_month
from app.reports.pdf import render_pdf

router = APIRouter(prefix="/datasets", tags=["reports"])


class ReportMonthOut(BaseModel):
    """A month that has data."""

    month: str
    label: str


class ReportMonthsOut(BaseModel):
    """Months a report can be made for, newest first, and the suggested one."""

    months: list[ReportMonthOut]
    default: str


@router.get("/{dataset_id}/report/months", response_model=ReportMonthsOut)
def report_months(
    dataset: Dataset = Depends(require_ready), storage: Storage = Depends(get_storage)
) -> ReportMonthsOut:
    """Months with data; the default is the latest complete month. General data has no
    months: its report covers the whole table."""
    if dataset.kind == "general":
        return ReportMonthsOut(months=[], default="")
    df = svc.load_clean(storage, dataset)
    months = available_months(df)[::-1]
    return ReportMonthsOut(
        months=[ReportMonthOut(month=m, label=month_label(m)) for m in months],
        default=default_month(df),
    )


def _pdf_response(pdf: bytes, name: str, suffix: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "data"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="InsightPulse-{safe}-{suffix}.pdf"'},
    )


def _data_report(dataset: Dataset, storage: Storage) -> Response:
    ex = svc.exploration(storage, dataset)
    prediction = None
    if ex.target:
        try:
            df = svc.load_clean(storage, dataset)
            prediction = predict_column(df, ex.target, svc.profile_kinds(dataset))
        except PredictError:
            prediction = None
    pdf = render_data_pdf(
        ex,
        dataset_name=dataset.name,
        filename=dataset.filename,
        cleaning=dataset.cleaning,
        prediction=prediction,
    )
    return _pdf_response(pdf, dataset.name, "data-report")


@router.get(
    "/{dataset_id}/report",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def monthly_report(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> Response:
    """A multi-page PDF for one month: KPIs, charts, data overview, findings, forecast.
    For general data, a data report (EDA, findings, what drives the outcome column)."""
    if dataset.kind == "general":
        return _data_report(dataset, storage)
    df = svc.load_clean(storage, dataset)
    ctx = svc.context_for(dataset, df)
    insights = svc.dataset_insights(storage, dataset)
    actions = [a.model_dump() for a in recommendations(dataset, db, storage, llm).actions]
    forecast, forecast_chart = None, None
    job = latest_job(db, dataset, "forecast", HOME_FORECAST)
    if job and job.status == "succeeded" and job.result:
        forecast = job.result
        fields = set(ForecastResult.model_fields)
        result = ForecastResult.model_validate({k: v for k, v in job.result.items() if k in fields})
        forecast_chart = forecast_chart_spec(result, ctx.currency)
    try:
        report = build_report(
            df,
            month or default_month(df),
            dataset_name=dataset.name,
            currency=ctx.currency,
            profile=dataset.profile,
            quality=dataset.quality,
            cleaning=dataset.cleaning,
            insights=insights,
            actions=actions,
            forecast=forecast,
            forecast_chart=forecast_chart,
        )
    except ReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _pdf_response(render_pdf(report), dataset.name, report.month)
