"""Customer segments: K-Means on log-scaled RFM, k chosen by silhouette score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.insights.base import ChartSpec, fmt_money, has, jsonable

K_RANGE = range(3, 7)


class SegmentsUnavailableError(ValueError):
    """Not enough customers to segment (message is user-facing)."""


class Segment(BaseModel):
    """One cluster, described in business terms."""

    name: str
    customers: int
    share_of_customers: float
    revenue_share: float
    avg_recency_days: float
    avg_orders: float
    avg_spend: float


class SegmentsResult(BaseModel):
    """K-Means segmentation output."""

    k: int
    silhouette: float
    segments: list[Segment]
    method: str


def rfm_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Recency (days), frequency (orders) and monetary (spend) per customer."""
    ref = df["date"].max().normalize() + pd.Timedelta(days=1)
    key = "order_id" if has(df, "order_id") else "date"
    g = df.dropna(subset=["customer"]).groupby("customer")
    return pd.DataFrame(
        {
            "recency": (ref - g["date"].max()).dt.days,
            "frequency": g[key].nunique(),
            "monetary": g["revenue"].sum(),
        }
    )


def _name_clusters(profile: pd.DataFrame) -> dict[int, str]:
    """Readable names from centroid ranks (VIP, Lapsed, New, Loyal, Regular, Occasional)."""
    z = (profile - profile.mean()) / profile.std(ddof=0).replace(0, 1)
    value = z["frequency"] + z["monetary"] - z["recency"]
    names: dict[int, str] = {}
    order = list(value.sort_values(ascending=False).index)
    names[order[0]] = "VIP"
    rest = [c for c in order if c not in names]
    lapsed = profile.loc[rest, "recency"].idxmax()
    names[lapsed] = "Lapsed"
    rest = [c for c in rest if c not in names]
    if rest:
        recent_low = profile.loc[rest].sort_values(["frequency", "recency"]).index[0]
        if profile.at[recent_low, "recency"] <= profile["recency"].median():
            names[recent_low] = "New"
    for c, label in zip(
        [c for c in order if c not in names], ["Loyal", "Regular", "Occasional"], strict=False
    ):
        names[c] = label
    return names


def kmeans_segments(df: pd.DataFrame, seed: int = 0) -> tuple[SegmentsResult, KMeans]:
    """Cluster customers; returns business-named segments and the fitted model."""
    if not has(df, "customer"):
        raise SegmentsUnavailableError("Segments need a customer column.")
    rfm = rfm_raw(df)
    if len(rfm) < 30:
        raise SegmentsUnavailableError("Need at least 30 customers to find segments.")
    X = StandardScaler().fit_transform(np.log1p(rfm.clip(lower=0)))
    rng = np.random.default_rng(seed)
    sample = rng.choice(len(X), size=min(3000, len(X)), replace=False)
    best: tuple[float, KMeans] | None = None
    for k in K_RANGE:
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
        score = float(silhouette_score(X[sample], km.labels_[sample]))
        if best is None or score > best[0]:
            best = (score, km)
    score, km = best
    rfm["cluster"] = km.labels_
    profile = rfm.groupby("cluster")[["recency", "frequency", "monetary"]].mean()
    names = _name_clusters(profile)
    total_rev = float(rfm["monetary"].sum()) or 1.0
    segs = []
    for c, grp in rfm.groupby("cluster"):
        segs.append(
            Segment(
                name=names[c],
                customers=len(grp),
                share_of_customers=round(len(grp) / len(rfm), 4),
                revenue_share=round(float(grp["monetary"].sum()) / total_rev, 4),
                avg_recency_days=round(float(grp["recency"].mean()), 1),
                avg_orders=round(float(grp["frequency"].mean()), 2),
                avg_spend=round(float(grp["monetary"].mean()), 2),
            )
        )
    segs.sort(key=lambda s: s.revenue_share, reverse=True)
    return (
        SegmentsResult(
            k=km.n_clusters,
            silhouette=round(score, 3),
            segments=segs,
            method="K-Means on log-scaled recency, frequency and spend",
        ),
        km,
    )


def segments_chart_spec(result: SegmentsResult, currency: str | None) -> ChartSpec:
    """Donut of revenue share by segment."""
    total = sum(s.avg_spend * s.customers for s in result.segments)
    return ChartSpec(
        kind="donut",
        payload=jsonable(
            {
                "labels": [s.name for s in result.segments],
                "values": [s.revenue_share for s in result.segments],
                "center_value": fmt_money(total, currency),
                "center_label": "Revenue",
            }
        ),
    )
