"""Forecast orchestration: time-based holdout, auto model selection by MAPE, refit.

The last 20% of days is held out (never shuffled). Each candidate is trained on the
first 80% and scored on the holdout by MAPE on 7-day totals (daily MAPE is dominated
by day-to-day noise and breaks on zero days). The winner is refit on all data.
With under ~60 days of history a simple trend is returned with a message instead.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.insights.base import ChartSpec, jsonable, pct_change, weekly_totals
from app.ml.models import CANDIDATES, Z80, Forecaster, TrendForecaster
from app.ml.series import TARGETS, daily_series

log = logging.getLogger(__name__)

MIN_HISTORY_DAYS = 60
MIN_ANY_DAYS = 14
HOLDOUT_FRACTION = 0.2


class ModelScore(BaseModel):
    """Holdout performance of one candidate."""

    model: str
    weekly_mape: float | None
    daily_mape: float | None
    total_error_pct: float | None
    ok: bool
    error: str | None = None


class ForecastResult(BaseModel):
    """A forecast plus everything the Forecast screen shows."""

    target: str
    target_label: str
    horizon_days: int
    model: str
    models_tried: list[ModelScore]
    selection_metric: str
    history_days: int
    holdout_days: int
    train_end: str | None
    holdout_start: str | None
    last_date: str
    dates: list[str]
    yhat: list[float]
    lower: list[float]
    upper: list[float]
    total: float
    total_lower: float
    total_upper: float
    previous_total: float | None
    change_pct: float | None
    accuracy_pct: float | None
    accuracy_note: str
    message: str | None = None
    history_dates: list[str]
    history_values: list[float]


def mape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    """Mean absolute percentage error in %, skipping zero actuals."""
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def weekly_blocks(values: np.ndarray) -> np.ndarray:
    """Sum consecutive 7-day blocks, dropping a trailing partial block."""
    n = len(values) // 7 * 7
    return values[:n].reshape(-1, 7).sum(axis=1) if n else values[:0]


def total_band_half_width(fc: pd.DataFrame, weekly_mape_pct: float | None = None) -> float:
    """80% half-width for the horizon *total*.

    Two estimates, and the wider one wins:

    * model band: days inside a 7-day block move together, blocks are independent
      (summing every daily bound would assume all days miss the same way);
    * measured accuracy: how far off weekly totals were on the holdout. Weeks within a
      month are treated as independent and months as moving together, because real
      forecast errors (a demand shift, a lost customer) persist for weeks.
    """
    half = ((fc["upper"] - fc["lower"]) / 2).to_numpy()
    blocks = [half[i : i + 7].sum() for i in range(0, len(half), 7)]
    model_half = float(np.sqrt(np.sum(np.square(blocks))))
    if weekly_mape_pct is None:
        return model_half
    weeks = max(1.0, len(fc) / 7)
    # MAPE ~ mean absolute error; sd ~ 1.25 x MAE for roughly normal errors.
    rel_sd = 1.25 * weekly_mape_pct / 100 / np.sqrt(min(weeks, 4.0))
    return max(model_half, float(Z80 * rel_sd * fc["yhat"].sum()))


def human_span(days: int) -> str:
    """'3 months', '5 weeks', '10 days'."""
    if days >= 60:
        n = round(days / 30)
        return f"{n} months"
    if days >= 14:
        return f"{round(days / 7)} weeks"
    return f"{days} days"


def score_candidate(name: str, train: pd.Series, test: pd.Series) -> ModelScore:
    """Fit ``name`` on train and score it on the holdout."""
    try:
        pred = CANDIDATES[name]().fit(train).predict(len(test))["yhat"].to_numpy()
    except Exception as exc:  # noqa: BLE001 - one failing model must not stop the others
        log.warning("Forecast candidate %s failed: %s", name, exc)
        return ModelScore(
            model=name,
            weekly_mape=None,
            daily_mape=None,
            total_error_pct=None,
            ok=False,
            error=type(exc).__name__,
        )
    actual = test.to_numpy()
    total_err = (abs(pred.sum() - actual.sum()) / actual.sum() * 100) if actual.sum() else None
    return ModelScore(
        model=name,
        weekly_mape=mape(weekly_blocks(actual), weekly_blocks(pred)),
        daily_mape=mape(actual, pred),
        total_error_pct=total_err,
        ok=True,
    )


def forecast(
    df: pd.DataFrame,
    target: str = "revenue",
    horizon_days: int = 90,
    candidates: tuple[str, ...] = ("prophet", "sarima", "xgboost"),
) -> tuple[ForecastResult, Forecaster]:
    """Forecast ``target`` for ``horizon_days``; returns the result and the fitted model."""
    y = daily_series(df, target)
    if len(y) < MIN_ANY_DAYS:
        raise ValueError(f"Need at least {MIN_ANY_DAYS} days of data to forecast.")

    if len(y) < MIN_HISTORY_DAYS:
        model: Forecaster = TrendForecaster().fit(y)
        fc = model.predict(horizon_days)
        return (
            _result(
                y,
                target,
                horizon_days,
                model.name,
                fc,
                scores=[],
                holdout=0,
                message=(
                    f"Only {len(y)} days of history. Forecasts need about "
                    f"{MIN_HISTORY_DAYS} days; this is a simple trend for now."
                ),
            ),
            model,
        )

    holdout = max(7, round(len(y) * HOLDOUT_FRACTION))
    train, test = y.iloc[:-holdout], y.iloc[-holdout:]
    scores = [score_candidate(name, train, test) for name in candidates]
    usable = [s for s in scores if s.ok and s.weekly_mape is not None]
    if not usable:
        model = TrendForecaster().fit(y)
        return (
            _result(
                y,
                target,
                horizon_days,
                model.name,
                model.predict(horizon_days),
                scores=scores,
                holdout=holdout,
                message="The forecasting models could not be fit; showing a trend.",
            ),
            model,
        )
    best = min(usable, key=lambda s: s.weekly_mape)
    model = CANDIDATES[best.model]().fit(y)
    return (
        _result(
            y,
            target,
            horizon_days,
            best.model,
            model.predict(horizon_days),
            scores=scores,
            holdout=holdout,
        ),
        model,
    )


def _result(
    y: pd.Series,
    target: str,
    horizon: int,
    model_name: str,
    fc: pd.DataFrame,
    scores: list[ModelScore],
    holdout: int,
    message: str | None = None,
) -> ForecastResult:
    previous = float(y.iloc[-horizon:].sum()) if len(y) >= horizon else None
    total = float(fc["yhat"].sum())
    chosen = next((s for s in scores if s.model == model_name), None)
    accuracy = chosen.weekly_mape if chosen else None
    total_half = total_band_half_width(fc, accuracy)
    if accuracy is not None:
        note = f"Within ±{round(accuracy)}% on the last {human_span(holdout)}"
    else:
        note = "Accuracy can't be measured yet: not enough history to test the model."
    window = min(len(y), max(56, min(horizon, 365)))
    hist = y.iloc[-window:]
    return ForecastResult(
        target=target,
        target_label=TARGETS[target],
        horizon_days=horizon,
        model=model_name,
        models_tried=scores,
        selection_metric="MAPE of 7-day totals on a time-based holdout (last 20%)",
        history_days=len(y),
        holdout_days=holdout,
        train_end=y.index[-holdout - 1].date().isoformat() if holdout else None,
        holdout_start=y.index[-holdout].date().isoformat() if holdout else None,
        last_date=y.index.max().date().isoformat(),
        dates=[d.date().isoformat() for d in fc.index],
        yhat=fc["yhat"].round(2).tolist(),
        lower=fc["lower"].round(2).tolist(),
        upper=fc["upper"].round(2).tolist(),
        total=round(total, 2),
        total_lower=round(max(0.0, total - total_half), 2),
        total_upper=round(total + total_half, 2),
        previous_total=round(previous, 2) if previous is not None else None,
        change_pct=pct_change(total, previous) if previous is not None else None,
        accuracy_pct=round(accuracy, 1) if accuracy is not None else None,
        accuracy_note=note,
        message=message,
        history_dates=[d.date().isoformat() for d in hist.index],
        history_values=hist.round(2).tolist(),
    )


def forecast_chart_spec(
    result: ForecastResult,
    currency: str | None = None,
    max_days: int | None = None,
    history_days: int | None = None,
) -> ChartSpec:
    """Actual history + dashed forecast + 80% band + 'Today' marker.

    Long horizons (> 120 days) are drawn as 7-day totals so the chart stays readable; the
    last actual point is always the last data day, which is where 'Today' sits.
    """
    h = min(result.horizon_days, max_days or result.horizon_days)
    hist = pd.Series(result.history_values, index=pd.to_datetime(result.history_dates))
    if history_days:
        hist = hist.iloc[-history_days:]
    fc = pd.DataFrame(
        {"yhat": result.yhat, "lower": result.lower, "upper": result.upper},
        index=pd.to_datetime(result.dates),
    ).iloc[:h]
    if h > 120:
        hist = weekly_totals(hist, anchor="end")
        fc = weekly_totals(fc, anchor="start")
    last_x, last_y = hist.index[-1], float(hist.iloc[-1])
    fx = [last_x, *fc.index]
    payload: dict[str, Any] = {
        "x": [d.strftime("%Y-%m-%d") for d in hist.index],
        "x_is_date": True,
        "series": [
            {"name": "Actual", "y": hist.round(2).tolist(), "role": "actual"},
            {
                "name": "Forecast",
                "x": [d.strftime("%Y-%m-%d") for d in fx],
                "y": [last_y, *fc["yhat"].round(2).tolist()],
                "role": "forecast",
            },
        ],
        "band": {
            "x": [d.strftime("%Y-%m-%d") for d in fx],
            "lower": [last_y, *fc["lower"].round(2).tolist()],
            "upper": [last_y, *fc["upper"].round(2).tolist()],
            "label": "Likely range",
            "role": "forecast",
        },
        "today": last_x.strftime("%Y-%m-%d"),
        "y_format": "money" if result.target == "revenue" else "number",
        "currency": currency,
    }
    return ChartSpec(kind="line", payload=jsonable(payload))
