"""KPI summary: latest complete month vs the month before."""

from __future__ import annotations

import pandas as pd

from app.insights.base import (
    Insight,
    InsightContext,
    clamp01,
    complete_months,
    fmt_change,
    fmt_money,
    has,
    jsonable,
    month_label,
    order_count,
    pct_change,
)


def month_kpis(df: pd.DataFrame) -> dict[str, float]:
    """Revenue, orders, average order value and active customers for a slice."""
    revenue = float(df["revenue"].sum())
    orders = order_count(df)
    kpis = {
        "revenue": revenue,
        "orders": float(orders),
        "avg_order_value": revenue / orders if orders else 0.0,
    }
    if has(df, "customer"):
        kpis["active_customers"] = float(df["customer"].nunique())
    return kpis


def kpi_summary(df: pd.DataFrame, ctx: InsightContext) -> Insight | None:
    """Compare the latest complete month with the previous one."""
    months = complete_months(df)
    if len(months) < 2:
        return None
    cur_m, prev_m = months.index[-1], months.index[-2]
    cur = month_kpis(df[df["month"] == cur_m])
    prev = month_kpis(df[df["month"] == prev_m])
    changes = {k: pct_change(v, prev.get(k, 0.0)) for k, v in cur.items()}
    rev_change = changes["revenue"] or 0.0

    headline = (
        f"Revenue was {fmt_money(cur['revenue'], ctx.currency)} in "
        f"{month_label(cur_m)}, {fmt_change(changes['revenue'], month_label(prev_m))}"
    )
    aov_change = changes["avg_order_value"]
    if aov_change is not None and abs(aov_change) >= abs(changes["orders"] or 0):
        driver = "bigger baskets" if aov_change > 0 else "smaller baskets"
    else:
        driver = "more orders" if (changes["orders"] or 0) > 0 else "fewer orders"
    why = (
        f"The change came mostly from {driver}: orders "
        f"{fmt_change(changes['orders'], 'the month before') or 'were steady'}, "
        f"average order value {fmt_change(aov_change, 'the month before') or 'was steady'}."
    )
    return Insight(
        id="kpi_summary",
        kind="kpi_summary",
        category="sales",
        tag="Monthly KPIs",
        headline=headline,
        why_it_matters=why,
        score=clamp01(0.55 + min(0.4, abs(rev_change) / 60)),
        data=jsonable(
            {
                "month": cur_m,
                "previous_month": prev_m,
                "current": cur,
                "previous": prev,
                "change_pct": changes,
                "currency": ctx.currency,
            }
        ),
        chart=None,
    )
