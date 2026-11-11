"""ML endpoints: forecast (background job), churn, what-if, segments, job status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import datasets as svc
from app.core.jobs import JobRunner, find_or_create_job
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_current_user, get_job_runner, get_storage, require_ready
from app.ml.churn import ChurnResult, ChurnUnavailableError, churn_chart_spec, train_churn
from app.ml.segments import (
    SegmentsResult,
    SegmentsUnavailableError,
    kmeans_segments,
    segments_chart_spec,
)
from app.ml.series import available_targets
from app.ml.service import get_or_train
from app.ml.whatif import WhatIfResult, WhatIfUnavailableError, run_scenario, train_whatif
from app.ml.whatif import whatif_chart_spec as _whatif_chart
from app.models import Dataset, Job, User
from app.schemas import ChurnIn, ForecastIn, JobOut, WhatIfIn

router = APIRouter(tags=["ml"])


class ChurnOut(ChurnResult):
    """Churn result plus its feature-importance chart."""

    chart_url: str | None


class WhatIfOut(WhatIfResult):
    """What-if result plus its SHAP chart."""

    chart_url: str | None


class SegmentsOut(SegmentsResult):
    """Segments plus a revenue-share donut."""

    chart_url: str | None


@router.post(
    "/datasets/{dataset_id}/forecast", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
def start_forecast(
    body: ForecastIn,
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    runner: JobRunner = Depends(get_job_runner),
) -> Job:
    """Queue a forecast; poll ``GET /jobs/{job_id}``. Identical requests reuse one job."""
    if body.target not in available_targets(svc.load_clean(storage, dataset)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{body.target}' can't be forecast for this dataset.",
        )
    job, created = find_or_create_job(db, dataset, "forecast", body.model_dump())
    if created:
        runner.submit(job.id)
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Job:
    """Job status and result (only the owner can see it)."""
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("/datasets/{dataset_id}/predict/churn", response_model=ChurnOut)
def predict_churn(
    body: ChurnIn | None = None,
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> ChurnOut:
    """Churn probabilities, at-risk customers and model quality (ROC AUC)."""
    window = body.churn_days if body else None
    df = svc.load_clean(storage, dataset)

    def train() -> tuple[Any, dict[str, Any]]:
        result, model = train_churn(df, window)
        return model, result.model_dump()

    try:
        bundle = get_or_train(storage, dataset, f"churn_w{window or 'auto'}", train)
    except ChurnUnavailableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    result = ChurnResult.model_validate(bundle["metrics"])
    out = ChurnOut(
        **result.model_dump(), chart_url=svc.register_chart(db, dataset, churn_chart_spec(result))
    )
    db.commit()
    return out


@router.post("/datasets/{dataset_id}/whatif", response_model=WhatIfOut)
def what_if(
    body: WhatIfIn,
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> WhatIfOut:
    """Estimated effect of a price or discount change (model trained once per version)."""
    df = svc.load_clean(storage, dataset)

    def train() -> tuple[Any, dict[str, Any]]:
        wm = train_whatif(df)
        return wm, wm.metrics

    try:
        bundle = get_or_train(storage, dataset, "whatif", train)
        result = run_scenario(bundle["model"], body.lever, body.change_pct)
    except WhatIfUnavailableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    out = WhatIfOut(
        **result.model_dump(), chart_url=svc.register_chart(db, dataset, _whatif_chart(result))
    )
    db.commit()
    return out


@router.get("/datasets/{dataset_id}/segments", response_model=SegmentsOut)
def segments(
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> SegmentsOut:
    """K-Means customer segments with business names."""
    df = svc.load_clean(storage, dataset)

    def train() -> tuple[Any, dict[str, Any]]:
        result, model = kmeans_segments(df)
        return model, result.model_dump()

    try:
        bundle = get_or_train(storage, dataset, "segments", train)
    except SegmentsUnavailableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    result = SegmentsResult.model_validate(bundle["metrics"])
    currency = (dataset.cleaning or {}).get("currency")
    out = SegmentsOut(
        **result.model_dump(),
        chart_url=svc.register_chart(db, dataset, segments_chart_spec(result, currency)),
    )
    db.commit()
    return out
