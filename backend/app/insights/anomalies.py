"""Daily revenue anomalies: points outside a trailing rolling mean +/- 3 std."""

from __future__ import annotations

import math

import pandas as pd

from app.insights.base import ChartSpec, Insight, InsightContext, clamp01, fmt_money, jsonable

WINDOW = 28
MIN_PERIODS = 14
Z = 3.0


def daily_revenue(df: pd.DataFrame) -> pd.Series:
    """Revenue per calendar day, with zero-filled gaps."""
    s = df.set_index("date")["revenue"].resample("D").sum()
    return s.asfreq("D", fill_value=0.0)


def detect_anomalies(daily: pd.Series) -> pd.DataFrame:
    """Return rolling bands and an ``is_anomaly`` flag for each day.

    The band for day *t* uses only days before *t*, so a spike cannot hide itself.
    A second pass recomputes the band with first-pass anomalies excluded, so one
    big spike does not widen the "normal range" for the following weeks.
    """
    out = _bands(daily, daily)
    cleaned = daily.where(~out["is_anomaly"])
    return _bands(daily, cleaned)


def _bands(daily: pd.Series, basis: pd.Series) -> pd.DataFrame:
    prior = basis.shift(1).rolling(WINDOW, min_periods=MIN_PERIODS)
    mean, std = prior.mean(), prior.std()
    out = pd.DataFrame(
        {"revenue": daily, "mean": mean, "lower": mean - Z * std, "upper": mean + Z * std}
    )
    out["z"] = ((daily - mean) / std.where(std > 0)).astype("float64")
    out["is_anomaly"] = (out["z"].abs() > Z).fillna(False) & out["mean"].notna()
    return out


def anomalies(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Flag unusual days, preferring recent and large deviations."""
    daily = daily_revenue(df)
    if len(daily) < WINDOW + 7:
        return None
    bands = detect_anomalies(daily)
    flagged = bands[bands["is_anomaly"]].copy()
    if flagged.empty:
        return None
    last_day = daily.index.max()
    flagged["days_ago"] = (last_day - flagged.index).days
    flagged["rank"] = flagged["z"].abs().astype(float) * (1 + 1 / (1 + flagged["days_ago"] / 30))
    top = flagged.sort_values("rank", ascending=False).head(5)
    lead = top.iloc[0]
    lead_day = top.index[0]
    kind = "spike" if lead["revenue"] > lead["mean"] else "drop"
    ratio = float(lead["revenue"] / lead["mean"]) if lead["mean"] else 0.0

    headline = (
        f"Unusual {kind} on {lead_day:%d %b %Y}: "
        f"{fmt_money(lead['revenue'], ctx.currency)} vs a typical "
        f"{fmt_money(lead['mean'], ctx.currency)}"
    )
    why = (
        "Check whether this was a bulk order, a promotion, a stock-out or a data error. "
        if kind == "spike"
        else "Check for outages, stock-outs, payment problems or missing data that day. "
    )
    why += f"{len(flagged)} unusual day{'s' if len(flagged) != 1 else ''} found in total."

    window = bands.loc[
        max(bands.index.min(), lead_day - pd.Timedelta(days=90)) : min(
            last_day, lead_day + pd.Timedelta(days=30)
        )
    ]
    marks = [d for d in window.index if bool(window.loc[d, "is_anomaly"])]
    chart = ChartSpec(
        kind="line",
        payload=jsonable(
            {
                "x": [d.strftime("%Y-%m-%d") for d in window.index],
                "x_is_date": True,
                "series": [
                    {"name": "Daily revenue", "y": window["revenue"].tolist(), "role": "actual"}
                ],
                "band": {
                    "lower": window["lower"].clip(lower=0).tolist(),
                    "upper": window["upper"].tolist(),
                    "label": "Normal range",
                },
                "highlights": [
                    {"x": d.strftime("%Y-%m-%d"), "y": float(window.loc[d, "revenue"])}
                    for d in marks
                ],
                "y_format": "money",
                "currency": ctx.currency,
            }
        ),
    )
    # Recent anomalies matter most: weight halves roughly every 3 weeks.
    recency = math.exp(-float(lead["days_ago"]) / 30)
    return Insight(
        id="anomalies",
        kind="anomalies",
        category="anomalies",
        tag="Anomaly",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.3 + 0.45 * recency + 0.2 * min(1.0, abs(float(lead["z"])) / 10)),
        data=jsonable(
            {
                "anomalies": [
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "revenue": float(r["revenue"]),
                        "expected": float(r["mean"]),
                        "z": float(r["z"]),
                        "type": "spike" if r["revenue"] > r["mean"] else "drop",
                    }
                    for d, r in top.iterrows()
                ],
                "total_flagged": int(len(flagged)),
                "lead_ratio_vs_typical": ratio,
                "method": f"trailing {WINDOW}-day mean +/- {Z:g} std",
                "currency": ctx.currency,
            }
        ),
        chart=chart,
    )
