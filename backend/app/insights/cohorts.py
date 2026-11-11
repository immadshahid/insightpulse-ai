"""Monthly cohort retention."""

from __future__ import annotations

import pandas as pd

from app.insights.base import (
    ChartSpec,
    Insight,
    InsightContext,
    clamp01,
    has,
    jsonable,
    month_label,
)

MAX_OFFSET = 6
MAX_COHORTS = 10


def retention_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Share of each first-purchase-month cohort active N months later (0..1)."""
    d = df.dropna(subset=["customer"])[["customer", "date"]].copy()
    d["period"] = d["date"].dt.to_period("M")
    first = d.groupby("customer")["period"].min().rename("cohort")
    d = d.join(first, on="customer")
    d["offset"] = (d["period"] - d["cohort"]).apply(lambda x: x.n)
    active = d.groupby(["cohort", "offset"])["customer"].nunique().unstack(fill_value=0)
    sizes = active[0]
    return active.div(sizes, axis=0)


def cohort_retention(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Report how many new customers come back in the following months."""
    if not has(df, "customer"):
        return None
    matrix = retention_matrix(df)
    if matrix.shape[0] < 3 or 1 not in matrix.columns:
        return None
    last_period = df["date"].max().to_period("M")
    # Only cohorts old enough to have a full month-1 / month-3 observation.
    m1 = matrix.loc[matrix.index <= last_period - 2, 1].mean() if 1 in matrix else float("nan")
    m3 = matrix.loc[matrix.index <= last_period - 4, 3].mean() if 3 in matrix else float("nan")
    m1 = float(m1)
    headline = f"About {m1 * 100:.0f}% of new customers buy again the next month"
    why = f"By month 3, {float(m3) * 100:.0f}% are still buying. " if pd.notna(m3) else ""
    why += (
        "Raising repeat purchase is usually the cheapest way to grow."
        if m1 < 0.3
        else "Retention is healthy; keep the post-purchase experience strong."
    )

    # Skip M0 (always 100%) so the colour scale shows real differences.
    shown = matrix.loc[:, [c for c in matrix.columns if 1 <= c <= MAX_OFFSET]]
    shown = shown.iloc[-(MAX_COHORTS + 1) : -1]
    values = [
        [
            (None if (c > (last_period - idx).n) else round(float(v) * 100, 1))
            for c, v in row.items()
        ]
        for idx, row in shown.iterrows()
    ]
    chart = ChartSpec(
        kind="heatmap",
        payload=jsonable(
            {
                "rows": [month_label(str(p)) for p in shown.index],
                "cols": [f"M{c}" for c in shown.columns],
                "values": values,
                "value_format": "percent",
                "annotate": True,
            }
        ),
    )
    return Insight(
        id="cohort_retention",
        kind="cohort_retention",
        category="customers",
        tag="Retention",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.3 + 0.45 * (1 - min(1.0, m1 / 0.5))),
        data=jsonable(
            {
                "month1_retention": m1,
                "month3_retention": float(m3) if pd.notna(m3) else None,
                "cohorts": [str(p) for p in shown.index],
                "matrix_pct": values,
            }
        ),
        chart=chart,
    )
