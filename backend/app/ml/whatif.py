"""What-if: estimate the effect of a price or discount change on units and revenue.

A gradient-boosting model (HistGradientBoostingRegressor, monotonic: higher price never
raises demand, a bigger discount never lowers it) learns units per order line from the
line's price relative to the product's usual price, discount, product, calendar and
trend. The scenario re-prices the last 30 days of order lines and compares predicted
units and revenue with the baseline.
SHAP values explain which factors drive demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score

from app.insights.base import ChartSpec, has, jsonable

Lever = Literal["price", "discount"]
FEATURES = ["rel_price", "discount", "product_code", "base_price", "weekday", "month", "t"]
LABELS = {
    "rel_price": "Price vs usual",
    "discount": "Discount",
    "product_code": "Product",
    "base_price": "Product price level",
    "weekday": "Weekday",
    "month": "Month",
    "t": "Trend over time",
}
SCENARIO_DAYS = 30
MAX_PRODUCT_CODES = 254


class WhatIfUnavailableError(ValueError):
    """The dataset can't support this what-if (message is user-facing)."""


@dataclass
class WhatIfModel:
    """A trained demand model plus what is needed to run scenarios."""

    model: HistGradientBoostingRegressor
    recent: pd.DataFrame
    has_discount: bool
    metrics: dict[str, float]
    shap_importance: list[dict[str, float | str]] = field(default_factory=list)


class WhatIfResult(BaseModel):
    """Scenario outcome for the slider."""

    lever: Lever
    change_pct: float
    period_days: int
    baseline_units: float
    scenario_units: float
    units_change_pct: float
    baseline_revenue: float
    scenario_revenue: float
    revenue_change_pct: float
    implied_elasticity: float | None
    model_r2_holdout: float
    shap_importance: list[dict[str, float | str]]
    notes: list[str]


def _price_column(df: pd.DataFrame) -> str | None:
    return next((c for c in df.columns if "price" in c and c != "base_price"), None)


def _discount_column(df: pd.DataFrame) -> str | None:
    return next((c for c in df.columns if "discount" in c), None)


def line_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Order lines with each line's own price relative to that product's usual price.

    Working per line (not per product-day) avoids a selection bias: daily average
    prices are most extreme on days with few sales, which would fake a price effect.
    """
    if not has(df, "quantity"):
        raise WhatIfUnavailableError("What-if needs a quantity column to learn how demand moves.")
    d = df[df["quantity"] > 0].copy()
    price_col, disc_col = _price_column(d), _discount_column(d)
    d["unit_price"] = d[price_col] if price_col else d["revenue"] / d["quantity"]
    d = d[d["unit_price"] > 0]
    d["discount"] = d[disc_col].fillna(0).clip(0, 90) if disc_col else 0.0
    d["product"] = d["product"].fillna("Other") if has(d, "product") else "All products"
    usual = d.groupby("product")["unit_price"].transform("median")
    d["rel_price"] = d["unit_price"] / usual
    d["base_price"] = np.log(usual)
    # The model handles at most 255 categories: keep the busiest products, group the rest.
    busiest = d["product"].value_counts().index[:MAX_PRODUCT_CODES]
    codes = {name: i for i, name in enumerate(busiest)}
    d["product_code"] = d["product"].map(codes).fillna(MAX_PRODUCT_CODES).astype(int)
    d["day"] = d["date"].dt.normalize()
    d["weekday"] = d["day"].dt.weekday
    d["month"] = d["day"].dt.month
    d["t"] = (d["day"] - d["day"].min()).dt.days
    return d.reset_index(drop=True), disc_col is not None


def train_whatif(df: pd.DataFrame) -> WhatIfModel:
    """Train the units-per-line model; validate on the last 20% of days (time-based)."""
    frame, has_discount = line_frame(df)
    days = np.sort(frame["day"].unique())
    if len(days) < 60 or len(frame) < 300:
        raise WhatIfUnavailableError("Need at least 60 days of sales to estimate price effects.")
    split = days[int(len(days) * 0.8)]
    train, test = frame[frame["day"] < split], frame[frame["day"] >= split]
    mono = [-1, 1, 0, 0, 0, 0, 0]  # price down-only, discount up-only
    params = {
        "max_iter": 200,
        "learning_rate": 0.05,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
        "monotonic_cst": mono,
        "categorical_features": [2],
        "random_state": 0,
    }
    holdout = HistGradientBoostingRegressor(**params).fit(train[FEATURES], train["quantity"])
    r2 = float(r2_score(test["quantity"], holdout.predict(test[FEATURES])))
    model = HistGradientBoostingRegressor(**params).fit(frame[FEATURES], frame["quantity"])
    recent = frame[frame["day"] > frame["day"].max() - pd.Timedelta(days=SCENARIO_DAYS)]
    wm = WhatIfModel(
        model=model,
        recent=recent.reset_index(drop=True),
        has_discount=has_discount,
        metrics={
            "r2_holdout": round(r2, 3),
            "quantity_std": round(float(frame["quantity"].std()), 3),
        },
    )
    wm.shap_importance = shap_importance(
        model, frame[FEATURES].sample(min(800, len(frame)), random_state=0)
    )
    return wm


def shap_importance(
    model: HistGradientBoostingRegressor, X: pd.DataFrame
) -> list[dict[str, float | str]]:
    """Mean |SHAP| per feature (units of daily demand), largest first."""
    import shap

    values = shap.TreeExplainer(model).shap_values(X)
    mean_abs = np.abs(values).mean(axis=0)
    pairs = sorted(zip(FEATURES, mean_abs, strict=True), key=lambda t: t[1], reverse=True)
    return [
        {"feature": f, "label": LABELS[f], "mean_abs_shap": round(float(v), 4)} for f, v in pairs
    ]


def run_scenario(wm: WhatIfModel, lever: Lever, change_pct: float) -> WhatIfResult:
    """Apply a price change (%) or discount change (percentage points) to recent sales."""
    if lever == "discount" and not wm.has_discount:
        raise WhatIfUnavailableError("This dataset has no discount column, so try a price change.")
    base = wm.recent.copy()
    scen = base.copy()
    if lever == "price":
        scen["rel_price"] = base["rel_price"] * (1 + change_pct / 100)
        scen["unit_price"] = base["unit_price"] * (1 + change_pct / 100)
    else:
        scen["discount"] = (base["discount"] + change_pct).clip(0, 90)
    u0 = np.clip(wm.model.predict(base[FEATURES]), 0, None)
    u1 = np.clip(wm.model.predict(scen[FEATURES]), 0, None)
    disc_factor = (lambda f: 1 - f["discount"] / 100) if wm.has_discount else (lambda f: 1.0)
    r0 = float(np.sum(u0 * base["unit_price"] * disc_factor(base)))
    r1 = float(np.sum(u1 * scen["unit_price"] * disc_factor(scen)))
    units_chg = (u1.sum() - u0.sum()) / u0.sum() * 100 if u0.sum() else 0.0
    rev_chg = (r1 - r0) / r0 * 100 if r0 else 0.0
    elasticity = units_chg / change_pct if lever == "price" and change_pct else None
    notes = [f"Based on the last {SCENARIO_DAYS} days of your product mix."]
    notes.append(
        "Assumes the same number of orders; it models how many units each order "
        "contains at the new price, not whether some customers stop ordering."
    )
    if wm.metrics.get("quantity_std", 1) < 0.3:
        notes.append(
            "Most orders contain a single unit, so price sensitivity is hard to see "
            "in this data; treat the result as a rough direction."
        )
    elif wm.metrics["r2_holdout"] < 0.02:
        notes.append(
            "Prices explain little of the variation in order size here; treat this "
            "as a rough direction rather than a precise number."
        )
    if lever == "price" and abs(change_pct) > 10:
        notes.append("Changes beyond ±10% go past the prices seen in your data.")
    return WhatIfResult(
        lever=lever,
        change_pct=change_pct,
        period_days=SCENARIO_DAYS,
        baseline_units=round(float(u0.sum()), 1),
        scenario_units=round(float(u1.sum()), 1),
        units_change_pct=round(float(units_chg), 2),
        baseline_revenue=round(r0, 2),
        scenario_revenue=round(r1, 2),
        revenue_change_pct=round(float(rev_chg), 2),
        implied_elasticity=round(float(elasticity), 2) if elasticity is not None else None,
        model_r2_holdout=wm.metrics["r2_holdout"],
        shap_importance=wm.shap_importance,
        notes=notes,
    )


def whatif_chart_spec(result: WhatIfResult) -> ChartSpec:
    """SHAP feature importance bars."""
    top = result.shap_importance[:6]
    return ChartSpec(
        kind="shap",
        payload=jsonable(
            {
                "features": [f["label"] for f in top],
                "values": [f["mean_abs_shap"] for f in top],
                "value_format": "number",
            }
        ),
    )
