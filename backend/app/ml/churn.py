"""Customer churn prediction with a balanced RandomForest, scored by ROC AUC.

Labelling avoids look-ahead: pick a cutoff ``window`` days before the last date,
compute features from data up to the cutoff, and label a customer as churned if they
bought nothing after it. The trained model then scores every customer using features
computed at the last date ("today").
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from app.insights.base import ChartSpec, has, jsonable

FEATURES = [
    "recency_days",
    "frequency",
    "monetary",
    "avg_order_value",
    "tenure_days",
    "avg_gap_days",
    "distinct_products",
    "orders_last_90",
    "revenue_share_last_90",
]
FEATURE_LABELS = {
    "recency_days": "Days since last order",
    "frequency": "Number of orders",
    "monetary": "Total spend",
    "avg_order_value": "Average order value",
    "tenure_days": "Customer age (days)",
    "avg_gap_days": "Typical gap between orders",
    "distinct_products": "Different products bought",
    "orders_last_90": "Orders in last 90 days",
    "revenue_share_last_90": "Share of spend in last 90 days",
}
MIN_CUSTOMERS = 50
MIN_PER_CLASS = 10


class ChurnUnavailableError(ValueError):
    """Not enough data to train a churn model (message is user-facing)."""


class AtRiskCustomer(BaseModel):
    """One customer with a high churn probability."""

    customer: str
    probability: float
    recency_days: int
    orders: int
    revenue_last_365: float


class ChurnResult(BaseModel):
    """Churn model output for the app."""

    churn_window_days: int
    cutoff_date: str
    model: str
    roc_auc: float
    base_churn_rate: float
    train_customers: int
    customers_scored: int
    risk_bands: dict[str, int]
    revenue_at_risk: float
    top_at_risk: list[AtRiskCustomer]
    feature_importance: list[dict[str, Any]]
    explanation: str


def customer_features(df: pd.DataFrame, ref: pd.Timestamp) -> pd.DataFrame:
    """Per-customer behaviour features using only rows strictly before ``ref``."""
    d = df[(df["date"] < ref) & df["customer"].notna()]
    order_key = "order_id" if has(d, "order_id") else "date"
    g = d.groupby("customer")
    first, last = g["date"].min(), g["date"].max()
    freq = g[order_key].nunique()
    monetary = g["revenue"].sum()
    recent = d[d["date"] >= ref - pd.Timedelta(days=90)].groupby("customer")
    tenure = (ref - first).dt.days
    out = pd.DataFrame(
        {
            "recency_days": (ref - last).dt.days,
            "frequency": freq,
            "monetary": monetary,
            "avg_order_value": monetary / freq,
            "tenure_days": tenure,
            "avg_gap_days": (last - first).dt.days / (freq - 1).where(freq > 1),
            "distinct_products": g["product"].nunique() if has(d, "product") else 1,
            "orders_last_90": recent[order_key].nunique(),
            "revenue_share_last_90": recent["revenue"].sum() / monetary,
        }
    )
    out["avg_gap_days"] = out["avg_gap_days"].fillna(out["tenure_days"])
    return out.fillna(0.0)


def choose_window(df: pd.DataFrame) -> int:
    """Churn window: about twice the median gap between repeat orders, 30-120 days."""
    order_key = "order_id" if has(df, "order_id") else "date"
    orders = df.dropna(subset=["customer"]).drop_duplicates(["customer", order_key])
    gaps = orders.sort_values("date").groupby("customer")["date"].diff().dt.days.dropna()
    if gaps.empty:
        return 60
    return int(np.clip(round(gaps.median() * 2 / 15) * 15, 30, 120))


def train_churn(
    df: pd.DataFrame, window_days: int | None = None
) -> tuple[ChurnResult, RandomForestClassifier]:
    """Train, evaluate (ROC AUC on a stratified 25% split) and score all customers."""
    if not has(df, "customer"):
        raise ChurnUnavailableError("Churn prediction needs a customer column.")
    window = window_days or choose_window(df)
    last = df["date"].max().normalize() + pd.Timedelta(days=1)
    cutoff = last - pd.Timedelta(days=window)
    if (cutoff - df["date"].min()).days < 60:
        raise ChurnUnavailableError(f"Need at least {window + 60} days of history to learn churn.")

    X = customer_features(df, cutoff)
    future_buyers = set(df.loc[df["date"] >= cutoff, "customer"].dropna())
    y = (~X.index.isin(list(future_buyers))).astype(int)
    if len(X) < MIN_CUSTOMERS or min(y.sum(), len(y) - y.sum()) < MIN_PER_CLASS:
        raise ChurnUnavailableError(
            "Not enough customers (or not enough who left) to train " "a churn model yet."
        )

    X_tr, X_te, y_tr, y_te = train_test_split(
        X[FEATURES], y, test_size=0.25, stratify=y, random_state=0
    )
    params = {
        "n_estimators": 300,
        "class_weight": "balanced",
        "min_samples_leaf": 3,
        "random_state": 0,
        "n_jobs": -1,
    }
    auc = float(
        roc_auc_score(
            y_te, RandomForestClassifier(**params).fit(X_tr, y_tr).predict_proba(X_te)[:, 1]
        )
    )
    model = RandomForestClassifier(**params).fit(X[FEATURES], y)

    now = customer_features(df, last)
    proba = pd.Series(model.predict_proba(now[FEATURES])[:, 1], index=now.index)
    year = df[df["date"] >= last - pd.Timedelta(days=365)].groupby("customer")["revenue"].sum()
    bands = {
        "high": int((proba >= 0.7).sum()),
        "medium": int(((proba >= 0.4) & (proba < 0.7)).sum()),
        "low": int((proba < 0.4).sum()),
    }
    high = proba[proba >= 0.7].index
    # "At risk" = high probability but still recently valuable, sorted by value at stake.
    ranked = (
        pd.DataFrame({"p": proba, "rev": year.reindex(proba.index).fillna(0)})
        .query("p >= 0.5")
        .sort_values(["rev", "p"], ascending=False)
        .head(10)
    )
    importance = sorted(
        zip(FEATURES, model.feature_importances_, strict=True), key=lambda t: t[1], reverse=True
    )
    top_feature = FEATURE_LABELS[importance[0][0]].lower()
    result = ChurnResult(
        churn_window_days=window,
        cutoff_date=cutoff.date().isoformat(),
        model="random_forest",
        roc_auc=round(auc, 3),
        base_churn_rate=round(float(y.mean()), 3),
        train_customers=int(len(X)),
        customers_scored=int(len(now)),
        risk_bands=bands,
        revenue_at_risk=round(float(year.reindex(high).fillna(0).sum()), 2),
        top_at_risk=[
            AtRiskCustomer(
                customer=str(c),
                probability=round(float(r.p), 3),
                recency_days=int(now.at[c, "recency_days"]),
                orders=int(now.at[c, "frequency"]),
                revenue_last_365=round(float(r.rev), 2),
            )
            for c, r in ranked.iterrows()
        ],
        feature_importance=[
            {"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(v), 4)}
            for f, v in importance
        ],
        explanation=(
            f"A customer counts as churned after {window} days without an order. "
            f"The model separates leavers from stayers with ROC AUC {auc:.2f} "
            f"(0.5 = guessing, 1.0 = perfect); {top_feature} matters most."
        ),
    )
    return result, model


def churn_chart_spec(result: ChurnResult) -> ChartSpec:
    """Feature importance bars."""
    top = result.feature_importance[:7]
    return ChartSpec(
        kind="shap",
        payload=jsonable(
            {
                "features": [f["label"] for f in top],
                "values": [f["importance"] for f in top],
                "value_format": "corr",
            }
        ),
    )
