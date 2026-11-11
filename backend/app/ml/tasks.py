"""Background job tasks for ML work."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core import datasets as svc
from app.core.jobs import JobError, task
from app.deps import get_storage
from app.ml.forecast import forecast, forecast_chart_spec
from app.ml.series import TargetError
from app.ml.store import save_model
from app.models import Dataset, Job


@task("forecast")
def forecast_task(db: Session, job: Job) -> dict[str, Any]:
    """Pick the best model on a holdout, forecast, save the model and register the chart."""
    dataset = db.get(Dataset, job.dataset_id)
    if dataset is None or dataset.status != "ready":
        raise JobError("The dataset is not ready.")
    storage = get_storage()
    df = svc.load_clean(storage, dataset)
    target, horizon = job.params["target"], int(job.params["horizon_days"])
    try:
        result, model = forecast(df, target, horizon)
    except TargetError as exc:
        raise JobError(str(exc)) from exc
    except ValueError as exc:  # e.g. too little data
        raise JobError(str(exc)) from exc
    metrics = result.model_dump(
        include={
            "model",
            "models_tried",
            "selection_metric",
            "holdout_days",
            "accuracy_pct",
            "history_days",
        }
    )
    save_model(
        storage,
        dataset.id,
        dataset.version,
        f"forecast_{target}_{horizon}",
        {"name": model.name, "state": model.export()},
        metrics,
    )
    ctx = svc.context_for(dataset, df)
    chart_url = svc.register_chart(db, dataset, forecast_chart_spec(result, ctx.currency))
    db.commit()
    return {**result.model_dump(), "currency": ctx.currency, "chart_url": chart_url}
