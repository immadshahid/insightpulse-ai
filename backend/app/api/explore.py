"""General data: Explore (EDA), Predict a column, and switching how a dataset is analysed."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import datasets as svc
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_owned_dataset, get_storage, require_general
from app.eda.predict import PredictError, predict_column, prediction_dict
from app.models import Dataset
from app.pipeline.mapping import MappingError
from app.schemas import DatasetOut, InsightOut

router = APIRouter(prefix="/datasets", tags=["explore"])


class ColumnOut(BaseModel):
    """One column's summary."""

    name: str
    kind: str
    missing_pct: float
    unique: int
    stats: list[dict[str, str]]
    top_values: list[dict[str, Any]]


class ExploreChartOut(BaseModel):
    """A chart image with its title and takeaway."""

    title: str
    caption: str
    url: str


class ExploreOut(BaseModel):
    """Full EDA of a general dataset."""

    dataset_id: str
    overview: dict[str, Any]
    quality: dict[str, Any]
    columns: list[ColumnOut]
    charts: list[ExploreChartOut]
    insights: list[InsightOut]
    target: str | None
    predictable: list[str]


class PredictIn(BaseModel):
    """The column to predict."""

    target: str = Field(min_length=1, max_length=300)


class PredictOut(BaseModel):
    """How well the column can be predicted, and what drives it."""

    target: str
    task: Literal["classification", "regression"]
    metric: str
    score: float
    baseline: float
    verdict: str
    rows_used: int
    features: list[dict[str, Any]]
    classes: list[dict[str, Any]]
    excluded: list[str] = []
    chart_url: str | None


class KindIn(BaseModel):
    """How to analyse the dataset."""

    kind: Literal["sales", "general"]


@router.get("/{dataset_id}/explore", response_model=ExploreOut)
def get_explore(
    target: str | None = Query(None, max_length=300),
    dataset: Dataset = Depends(require_general),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> ExploreOut:
    """Overview, column summaries, charts and findings; ``target`` focuses on one outcome."""
    result = svc.exploration(storage, dataset, target)
    out = ExploreOut(
        dataset_id=dataset.id,
        overview=result.overview,
        quality=result.quality,
        columns=[
            ColumnOut(
                name=c.name,
                kind=c.kind,
                missing_pct=c.missing_pct,
                unique=c.unique,
                stats=[{"label": k, "value": v} for k, v in c.stats],
                top_values=[{"value": v, "count": n, "share": s} for v, n, s in c.top_values],
            )
            for c in result.columns
        ],
        charts=[
            ExploreChartOut(
                title=c.title, caption=c.caption, url=svc.register_chart(db, dataset, c.spec)
            )
            for c in result.charts
        ],
        insights=[svc.insight_out(db, dataset, i) for i in result.insights],
        target=result.target,
        predictable=result.predictable,
    )
    db.commit()
    return out


@router.post("/{dataset_id}/predict", response_model=PredictOut)
def predict(
    body: PredictIn,
    dataset: Dataset = Depends(require_general),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> PredictOut:
    """Train a model for one column (5-fold cross-validated) and explain what drives it."""
    df = svc.load_clean(storage, dataset)
    try:
        result = predict_column(df, body.target, svc.profile_kinds(dataset))
    except PredictError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    out = PredictOut(
        **prediction_dict(result), chart_url=svc.register_chart(db, dataset, result.chart)
    )
    db.commit()
    return out


@router.put("/{dataset_id}/kind", response_model=DatasetOut)
def set_kind(
    body: KindIn,
    dataset: Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> DatasetOut:
    """Analyse the dataset as sales data or as general data."""
    try:
        svc.set_kind(db, storage, dataset, body.kind)
    except MappingError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{exc} Pick the date and revenue columns on the Data tab first.",
        ) from exc
    return svc.dataset_out(dataset)
