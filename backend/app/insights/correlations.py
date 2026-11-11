"""Correlations between numeric measures (order level)."""

from __future__ import annotations

import pandas as pd

from app.insights.base import ChartSpec, Insight, InsightContext, clamp01, jsonable

_EXCLUDE = {"weekday_num", "hour", "postal_code", "postcode", "zip", "zip_code", "zipcode"}
MIN_ABS_R = 0.2


def _mechanical(a: str, b: str) -> bool:
    """Pairs that are correlated by definition (revenue = price x quantity)."""
    pair = {a, b}
    return "revenue" in pair and bool(pair & {"quantity"} or any("price" in c for c in pair))


def _pretty(col: str) -> str:
    return col.replace("_pct", " %").replace("_", " ").capitalize()


def correlations(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Find the strongest non-trivial correlation among numeric columns."""
    cols = [
        c for c in df.select_dtypes("number").columns if c not in _EXCLUDE and df[c].nunique() > 2
    ]
    if len(cols) < 2:
        return None
    corr = df[cols].corr(method="pearson")
    pairs = [
        (a, b, float(corr.loc[a, b]))
        for i, a in enumerate(cols)
        for b in cols[i + 1 :]
        if pd.notna(corr.loc[a, b]) and not _mechanical(a, b)
    ]
    if not pairs:
        return None
    a, b, r = max(pairs, key=lambda p: abs(p[2]))
    if abs(r) < MIN_ABS_R:
        return None
    strength = "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.4 else "weak"
    direction = "rises" if r > 0 else "falls"
    headline = f"When {_pretty(a).lower()} goes up, {_pretty(b).lower()} {direction}"
    why = (
        f"A {strength} link (r = {r:.2f}). Correlation is not proof of cause, "
        "but it is worth testing."
    )
    labels = [_pretty(c) for c in cols]
    chart = ChartSpec(
        kind="corr_heatmap",
        payload=jsonable(
            {
                "labels": labels,
                "matrix": corr.round(3).to_numpy().tolist(),
            }
        ),
    )
    return Insight(
        id="correlations",
        kind="correlations",
        category="sales",
        tag="Drivers",
        headline=headline,
        why_it_matters=why,
        score=clamp01(abs(r) * 0.8),
        data=jsonable(
            {
                "pair": [a, b],
                "r": r,
                "strength": strength,
                "columns": cols,
                "matrix": corr.round(3).to_numpy().tolist(),
            }
        ),
        chart=chart,
    )
