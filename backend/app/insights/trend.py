"""Monthly revenue trend."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.insights.base import (
    ChartSpec,
    Insight,
    InsightContext,
    clamp01,
    complete_months,
    fmt_money,
    jsonable,
    month_label,
)


def monthly_trend(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Fit a straight line to monthly revenue and report the average monthly growth."""
    months = complete_months(df)
    if len(months) < 3:
        return None
    y = months.to_numpy(dtype=float)
    x = np.arange(len(y))
    slope, intercept = np.polyfit(x, y, 1)
    growth_pct = float(slope / y.mean() * 100) if y.mean() else 0.0
    best = months.idxmax()
    worst = months.idxmin()

    if growth_pct > 1:
        headline = f"Revenue is growing about {growth_pct:.1f}% a month"
    elif growth_pct < -1:
        headline = f"Revenue is falling about {abs(growth_pct):.1f}% a month"
    else:
        headline = "Revenue has been broadly flat month to month"
    why = (
        f"Best month was {month_label(best)} ({fmt_money(months[best], ctx.currency)}); "
        f"weakest was {month_label(worst)} ({fmt_money(months[worst], ctx.currency)})."
    )

    fitted = intercept + slope * x
    chart = ChartSpec(
        kind="line",
        payload=jsonable(
            {
                "x": [f"{m}-01" for m in months.index],
                "x_is_date": True,
                "series": [
                    {"name": "Revenue", "y": y.tolist(), "role": "actual"},
                    {"name": "Trend", "y": fitted.tolist(), "role": "baseline"},
                ],
                "y_format": "money",
                "currency": ctx.currency,
                "markers": "points",
            }
        ),
    )
    return Insight(
        id="monthly_trend",
        kind="monthly_trend",
        category="sales",
        tag="Sales trend",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.3 + min(0.6, abs(growth_pct) / 8)),
        data=jsonable(
            {
                "months": list(months.index),
                "revenue": y.tolist(),
                "avg_monthly_growth_pct": round(growth_pct, 2),
                "best_month": best,
                "worst_month": worst,
                "currency": ctx.currency,
            }
        ),
        chart=chart,
    )
