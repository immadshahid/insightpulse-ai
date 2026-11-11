"""Weekday x time-of-day sales pattern."""

from __future__ import annotations

import pandas as pd

from app.insights.base import ChartSpec, Insight, InsightContext, clamp01, jsonable
from app.pipeline.cleaner import WEEKDAYS

DAYPARTS = ["Morning", "Afternoon", "Evening", "Night"]
_FULL_DAY = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}


def daypart(hour: int) -> str:
    """Morning 6-12, Afternoon 12-17, Evening 17-22, Night otherwise."""
    if 6 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Night"


def weekday_time_pattern(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Average daily revenue by weekday (and daypart when times are known)."""
    if df["date"].dt.normalize().nunique() < 14:
        return None
    n_weeks = max(1.0, (df["date"].max() - df["date"].min()).days / 7)

    if ctx.has_time and "hour" in df.columns:
        parts = df["hour"].map(daypart)
        grid = (
            df.assign(daypart=parts)
            .pivot_table(
                index="weekday", columns="daypart", values="revenue", aggfunc="sum", fill_value=0.0
            )
            .reindex(index=WEEKDAYS, columns=DAYPARTS, fill_value=0.0)
        ) / n_weeks
        peak_day, peak_part = grid.stack().idxmax()
        peak = float(grid.loc[peak_day, peak_part])
        mean = float(grid.to_numpy().mean())
        headline = f"{_FULL_DAY[peak_day]} {peak_part.lower()}s are your busiest time"
        chart = ChartSpec(
            kind="heatmap",
            payload=jsonable(
                {
                    "rows": WEEKDAYS,
                    "cols": DAYPARTS,
                    "values": grid.to_numpy().tolist(),
                    "value_format": "money",
                    "currency": ctx.currency,
                    "annotate": True,
                }
            ),
        )
        slot = f"{_FULL_DAY[peak_day]} {peak_part.lower()}"
    else:
        by_day = df.groupby("weekday")["revenue"].sum().reindex(WEEKDAYS, fill_value=0.0) / n_weeks
        peak_day = str(by_day.idxmax())
        peak = float(by_day.max())
        mean = float(by_day.mean())
        headline = f"{_FULL_DAY[peak_day]} is your busiest day"
        chart = ChartSpec(
            kind="bar_ranking",
            payload=jsonable(
                {
                    "labels": WEEKDAYS,
                    "values": by_day.tolist(),
                    "highlight": [WEEKDAYS.index(peak_day)],
                    "value_format": "money",
                    "currency": ctx.currency,
                    "keep_order": True,
                    "horizontal": False,
                }
            ),
        )
        grid = by_day.to_frame("revenue")
        slot = _FULL_DAY[peak_day]

    lift = peak / mean if mean else 1.0
    by_weekday = df.groupby("weekday")["revenue"].sum().reindex(WEEKDAYS, fill_value=0.0)
    quiet_day = _FULL_DAY[str(by_weekday.idxmin())]
    why = (
        f"{slot} sells {lift:.1f}x an average slot; {quiet_day} is the quietest day. "
        "Time promotions and staffing around the peak."
    )
    return Insight(
        id="weekday_time_pattern",
        kind="weekday_time_pattern",
        category="sales",
        tag="Timing",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.2 + min(0.6, (lift - 1) / 2.5)),
        data=jsonable(
            {
                "peak_slot": slot,
                "peak_avg_weekly_revenue": peak,
                "avg_slot_weekly_revenue": mean,
                "lift": lift,
                "quietest_day": quiet_day,
                "grid": grid.round(2).to_dict(),
                "currency": ctx.currency,
            }
        ),
        chart=chart,
    )
