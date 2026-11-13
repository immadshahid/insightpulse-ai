"""Predict any column from the others, and explain what drives it.

A gradient-boosting model (handles missing values itself) is scored with 5-fold
cross-validation against a simple baseline (always guessing the most common outcome, or the
average), so the user can see whether the model actually learned something. Feature
importance is measured by permutation on the original columns, so it stays readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split

from app.eda.explore import column_kinds, outcome_copies
from app.insights.base import ChartSpec, jsonable

MAX_ROWS = 50_000
MAX_CATEGORIES = 30  # per feature; rarer values are grouped
MAX_CLASSES = 15


class PredictError(ValueError):
    """The column can't be predicted (message is shown to the user)."""


@dataclass
class Prediction:
    """How well a column can be predicted, and from what."""

    target: str
    task: str  # classification | regression
    metric_name: str
    score: float
    baseline: float
    verdict: str
    rows_used: int
    features: list[tuple[str, float]]  # column, share of importance (0..1)
    chart: ChartSpec | None
    classes: list[tuple[str, float]]  # outcome, share of rows (classification)
    excluded: list[str] = field(default_factory=list)  # columns that restate the target


def _encode(df: pd.DataFrame, columns: list[str], kinds: dict[str, str]) -> pd.DataFrame:
    """Numbers stay numbers; categories become codes (rare values grouped); dates become days."""
    out = pd.DataFrame(index=df.index)
    for col in columns:
        s = df[col]
        if kinds[col] == "numeric":
            out[col] = pd.to_numeric(s, errors="coerce")
        elif kinds[col] == "date":
            out[col] = (pd.to_datetime(s, errors="coerce") - pd.Timestamp("1970-01-01")).dt.days
        else:
            text = s.astype("string")
            keep = text.value_counts().head(MAX_CATEGORIES).index
            text = text.where(text.isin(keep), "Other")
            out[col] = text.astype("category").cat.codes.replace(-1, np.nan)
    return out


def predict_column(
    df: pd.DataFrame, target: str, profile_kinds: dict[str, str] | None = None
) -> Prediction:
    """Train and score a model for ``target``; raises PredictError when it can't be done."""
    if target not in df.columns:
        raise PredictError(f"There is no column called {target}.")
    kinds = column_kinds(df, profile_kinds or {})
    if kinds[target] in ("id", "text", "date"):
        raise PredictError(
            f"{target} looks like an ID, free text or a date, so it can't be predicted."
        )
    data = df[df[target].notna()]
    if len(data) > MAX_ROWS:
        data = data.sample(MAX_ROWS, random_state=0)
    if len(data) < 30:
        raise PredictError(f"Need at least 30 rows with {target} filled in.")
    y_raw = data[target]
    if y_raw.nunique() < 2:
        raise PredictError(f"{target} has only one value, so there is nothing to predict.")
    excluded = outcome_copies(data, target, kinds)
    features = [
        c
        for c, k in kinds.items()
        if c != target and c not in excluded and k in ("numeric", "category", "yes/no", "date")
    ]
    if not features:
        raise PredictError("There are no other usable columns to predict from.")
    x = _encode(data, features, kinds)
    x = x.loc[:, x.notna().any()]
    features = list(x.columns)
    categorical = [i for i, c in enumerate(features) if kinds[c] in ("category", "yes/no")]

    classification = kinds[target] in ("category", "yes/no")
    classes: list[tuple[str, float]] = []
    if classification:
        y_text = y_raw.astype(str)
        counts = y_text.value_counts()
        if len(counts) > MAX_CLASSES:
            raise PredictError(
                f"{target} has {len(counts)} different values; predict up to {MAX_CLASSES}."
            )
        rare = counts[counts < 5].index
        if len(rare):
            keep = ~y_text.isin(rare)
            x, y_text = x[keep], y_text[keep]
            counts = y_text.value_counts()
        if len(counts) < 2:
            raise PredictError(f"{target} has too few rows of each outcome to learn from.")
        classes = [(str(k), round(float(v) / len(y_text), 4)) for k, v in counts.items()]
        y = y_text.astype("category").cat.codes
        model = HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.08,
            categorical_features=categorical or None,
            random_state=0,
        )
        folds = StratifiedKFold(n_splits=min(5, int(counts.min())), shuffle=True, random_state=0)
        score = float(cross_val_score(model, x, y, cv=folds, scoring="accuracy").mean())
        baseline = float(counts.iloc[0] / counts.sum())
        metric = "accuracy"
        scoring = "accuracy"
    else:
        y = pd.to_numeric(y_raw, errors="coerce")
        keep = y.notna()
        x, y = x[keep], y[keep]
        model = HistGradientBoostingRegressor(
            max_iter=200,
            learning_rate=0.08,
            categorical_features=categorical or None,
            random_state=0,
        )
        folds = KFold(n_splits=5, shuffle=True, random_state=0)
        score = float(cross_val_score(model, x, y, cv=folds, scoring="r2").mean())
        baseline = 0.0
        metric = "r2"
        scoring = "r2"

    # Importance on a held-out part, measured on the original columns.
    stratify = y if classification else None
    x_tr, x_te, y_tr, y_te = train_test_split(
        x, y, test_size=0.25, random_state=0, stratify=stratify
    )
    fitted = model.fit(x_tr, y_tr)
    imp = permutation_importance(fitted, x_te, y_te, scoring=scoring, n_repeats=5, random_state=0)
    raw_imp = np.clip(imp.importances_mean, 0, None)
    total = raw_imp.sum()
    shares = raw_imp / total if total > 0 else raw_imp
    ranked = sorted(zip(features, shares, strict=True), key=lambda p: -p[1])
    top = [(c, round(float(s), 4)) for c, s in ranked if s > 0][:8]

    chart = None
    if top:
        chart = ChartSpec(
            kind="bar_ranking",
            payload=jsonable(
                {
                    "labels": [c for c, _ in top],
                    "values": [round(s * 100, 1) for _, s in top],
                    "highlight": [0],
                    "value_format": "percent",
                }
            ),
        )
    return Prediction(
        target=target,
        task="classification" if classification else "regression",
        metric_name=metric,
        score=round(score, 4),
        baseline=round(baseline, 4),
        verdict=_verdict(classification, score, baseline, target, top),
        rows_used=int(len(x)),
        features=top,
        chart=chart,
        classes=classes,
        excluded=excluded,
    )


def _verdict(classification: bool, score: float, baseline: float, target: str, top: list) -> str:
    lead = f" The column that matters most is {top[0][0]}." if top else ""
    if classification:
        gain = (score - baseline) * 100
        if gain >= 10:
            return (
                f"The model predicts {target} correctly {score * 100:.0f}% of the time, "
                f"well above the {baseline * 100:.0f}% you'd get by always guessing the most "
                f"common outcome.{lead}"
            )
        if gain >= 3:
            return (
                f"The model gets {target} right {score * 100:.0f}% of the time, a little better "
                f"than guessing ({baseline * 100:.0f}%).{lead}"
            )
        return (
            f"The other columns barely help predict {target} ({score * 100:.0f}% vs "
            f"{baseline * 100:.0f}% by guessing). It may depend on things not in this file."
        )
    if score >= 0.5:
        return f"The model explains {score * 100:.0f}% of the variation in {target}.{lead}"
    if score >= 0.15:
        return f"The model explains some of {target} ({score * 100:.0f}% of the variation).{lead}"
    share = max(score, 0) * 100
    return f"The other columns explain little of {target} ({share:.0f}% of the variation)."


def prediction_dict(p: Prediction) -> dict[str, Any]:
    """JSON-friendly form for the API."""
    return {
        "target": p.target,
        "task": p.task,
        "metric": p.metric_name,
        "score": p.score,
        "baseline": p.baseline,
        "verdict": p.verdict,
        "rows_used": p.rows_used,
        "features": [{"column": c, "importance": s} for c, s in p.features],
        "classes": [{"value": v, "share": s} for v, s in p.classes],
        "excluded": p.excluded,
    }
