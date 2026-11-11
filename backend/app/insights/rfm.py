"""RFM (recency, frequency, monetary) customer segmentation."""

from __future__ import annotations

import pandas as pd

from app.insights.base import ChartSpec, Insight, InsightContext, clamp01, fmt_money, has, jsonable

SEGMENT_ORDER = ["Champions", "Loyal", "Potential", "New", "At risk", "Hibernating"]


def rfm_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per customer: recency_days, frequency, monetary, R/F/M scores, segment."""
    ref = df["date"].max().normalize() + pd.Timedelta(days=1)
    order_key = "order_id" if has(df, "order_id") else "date"
    g = df.dropna(subset=["customer"]).groupby("customer")
    rfm = pd.DataFrame(
        {
            "recency_days": (ref - g["date"].max()).dt.days,
            "frequency": g[order_key].nunique(),
            "monetary": g["revenue"].sum(),
        }
    )
    rfm["r"] = _quintile(-rfm["recency_days"])
    rfm["f"] = _quintile(rfm["frequency"])
    rfm["m"] = _quintile(rfm["monetary"])
    rfm["segment"] = rfm.apply(_segment, axis=1)
    return rfm


def _quintile(s: pd.Series) -> pd.Series:
    """Score 1 (worst) .. 5 (best) by rank, robust to ties."""
    return pd.qcut(s.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)


def _segment(row: pd.Series) -> str:
    r, f = row["r"], row["f"]
    if r >= 4 and f >= 4:
        return "Champions"
    if r >= 3 and f >= 4:
        return "Loyal"
    if r >= 4 and row["frequency"] <= 1:
        return "New"
    if r <= 2 and f >= 3:
        return "At risk"
    if r <= 2:
        return "Hibernating"
    return "Potential"


def rfm_segments(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Segment customers and flag valuable customers who have gone quiet."""
    if not has(df, "customer") or df["customer"].nunique() < 20:
        return None
    rfm = rfm_table(df)
    total_rev = float(rfm["monetary"].sum()) or 1.0
    seg = (
        rfm.groupby("segment")
        .agg(
            customers=("monetary", "size"),
            revenue=("monetary", "sum"),
            avg_recency_days=("recency_days", "mean"),
        )
        .reindex(SEGMENT_ORDER)
        .dropna(how="all")
        .fillna(0)
    )
    seg["revenue_share"] = seg["revenue"] / total_rev

    at_risk = seg.loc["At risk"] if "At risk" in seg.index else None
    at_risk_n = int(at_risk["customers"]) if at_risk is not None else 0
    at_risk_share = float(at_risk["revenue_share"]) if at_risk is not None else 0.0
    champions_share = (
        float(seg.loc["Champions", "revenue_share"]) if "Champions" in seg.index else 0.0
    )

    if at_risk_n:
        headline = (
            f"{at_risk_n:,} once-regular customers have gone quiet "
            f"({at_risk_share * 100:.0f}% of lifetime revenue)"
        )
        why = (
            f"They bought often but not for about {at_risk['avg_recency_days']:.0f} days. "
            f"A win-back offer is cheaper than finding new buyers. Champions bring "
            f"{champions_share * 100:.0f}% of revenue."
        )
    else:
        headline = f"Champions bring {champions_share * 100:.0f}% of revenue"
        why = "Keep your most frequent, recent buyers happy; they carry the business."

    chart = ChartSpec(
        kind="donut",
        payload=jsonable(
            {
                "labels": list(seg.index),
                "values": seg["revenue"].tolist(),
                "center_label": "Revenue",
                "center_value": fmt_money(total_rev, ctx.currency),
                "value_format": "percent_of_total",
            }
        ),
    )
    return Insight(
        id="rfm_segments",
        kind="rfm_segments",
        category="customers",
        tag="Customers",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.35 + min(0.55, at_risk_share * 2.5)),
        data=jsonable(
            {
                "segments": seg.round(4).reset_index().to_dict(orient="records"),
                "customer_count": int(len(rfm)),
                "at_risk_customers": at_risk_n,
                "at_risk_revenue_share": at_risk_share,
                "currency": ctx.currency,
            }
        ),
        chart=chart,
    )
