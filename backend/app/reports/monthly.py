"""Numbers, charts and data-quality summary for one month's report.

Everything here is computed with pandas from the cleaned data; the PDF layer
(:mod:`app.reports.pdf`) only lays it out. No AI is needed, so a report can always be made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.insights.base import (
    ChartSpec,
    Insight,
    compact_number,
    fmt_money,
    has,
    jsonable,
    month_label,
    order_count,
    pct_change,
)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS_SHOWN = 12
MAX_COLUMNS_LISTED = 16  # fits the data-overview page together with the summaries


class ReportError(ValueError):
    """The month can't be reported (message is shown to the user)."""


@dataclass
class Kpi:
    """One headline number with its change against last month and last year."""

    label: str
    value: float
    display: str
    vs_prev: float | None
    vs_year: float | None


@dataclass
class ReportChart:
    """A chart with a title and a one-line takeaway."""

    title: str
    caption: str
    spec: ChartSpec


@dataclass
class MonthlyReport:
    """Everything the PDF shows for one month."""

    dataset_name: str
    month: str
    month_label: str
    first_day: str
    last_day: str
    currency: str | None
    headline: str
    kpis: list[Kpi]
    charts: list[ReportChart]
    rankings: dict[str, list[tuple[str, str, str]]]  # title -> (label, value, share)
    customers: dict[str, str] | None
    revenue_stats: list[tuple[str, str]]
    eda: dict[str, Any]
    insights: list[Insight] = field(default_factory=list)
    actions: list[dict[str, str]] = field(default_factory=list)
    forecast: dict[str, Any] | None = None
    forecast_chart: ChartSpec | None = None


# ------------------------------------------------------------------ months


def available_months(df: pd.DataFrame) -> list[str]:
    """Months that have data, oldest first ('2026-10')."""
    return sorted(df["date"].dt.to_period("M").astype(str).unique().tolist())


def default_month(df: pd.DataFrame) -> str:
    """The latest month that is (nearly) complete: data to the 30th of 31 days counts."""
    last = df["date"].max()
    months = available_months(df)
    current = last.to_period("M")
    if last.day >= last.days_in_month - 1 or len(months) == 1:
        return str(current)
    previous = str(current - 1)
    return previous if previous in months else str(current)


# ------------------------------------------------------------------ helpers


def _slice(df: pd.DataFrame, month: pd.Period) -> pd.DataFrame:
    return df[df["date"].dt.to_period("M") == month]


def _metrics(d: pd.DataFrame) -> dict[str, float]:
    revenue = float(d["revenue"].sum())
    orders = float(order_count(d)) if len(d) else 0.0
    out = {
        "revenue": revenue,
        "orders": orders,
        "aov": revenue / orders if orders else 0.0,
    }
    if has(d, "customer"):
        out["customers"] = float(d["customer"].nunique())
    if has(d, "quantity"):
        out["units"] = float(d["quantity"].sum())
    return out


def _change(cur: float, prev: dict[str, float] | None, key: str) -> float | None:
    if not prev or not prev.get(key):
        return None
    return pct_change(cur, prev[key])


def _number(value: float) -> str:
    return compact_number(value) if abs(value) >= 10_000 else f"{value:,.0f}"


def _orders(d: pd.DataFrame) -> pd.Series:
    """Revenue per order (or per line when there is no order id)."""
    if has(d, "order_id"):
        return d.groupby("order_id")["revenue"].sum()
    return d["revenue"]


def _ranking(d: pd.DataFrame, col: str, currency: str | None, n: int = 8):
    totals = d.groupby(col)["revenue"].sum().sort_values(ascending=False)
    total = float(totals.sum()) or 1.0
    rows = [
        (str(k), fmt_money(float(v), currency), f"{float(v) / total * 100:.0f}%")
        for k, v in totals.head(n).items()
    ]
    return totals.head(n), rows


# ------------------------------------------------------------------ report


def build_report(
    df: pd.DataFrame,
    month: str,
    *,
    dataset_name: str,
    currency: str | None,
    profile: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    cleaning: dict[str, Any] | None = None,
    insights: list[Insight] | None = None,
    actions: list[dict[str, str]] | None = None,
    forecast: dict[str, Any] | None = None,
    forecast_chart: ChartSpec | None = None,
) -> MonthlyReport:
    """Compute the report for ``month`` ('YYYY-MM'); raises ReportError if it has no data."""
    try:
        period = pd.Period(month, freq="M")
    except (ValueError, TypeError) as exc:
        raise ReportError("Choose a month like 2026-10.") from exc
    cur = _slice(df, period)
    if cur.empty:
        raise ReportError(f"There is no data for {month_label(str(period))}.")
    prev_df = _slice(df, period - 1)
    year_df = _slice(df, period - 12)
    m = _metrics(cur)
    prev = _metrics(prev_df) if len(prev_df) else None
    year = _metrics(year_df) if len(year_df) else None

    labels = {
        "revenue": "Revenue",
        "orders": "Orders",
        "aov": "Avg order value",
        "customers": "Customers",
        "units": "Units sold",
    }
    kpis = [
        Kpi(
            labels[k],
            v,
            fmt_money(v, currency) if k in ("revenue", "aov") else _number(v),
            _change(v, prev, k),
            _change(v, year, k),
        )
        for k, v in m.items()
    ]

    label = month_label(str(period))
    headline = f"Revenue in {label} was {fmt_money(m['revenue'], currency)}"
    if (c := _change(m["revenue"], prev, "revenue")) is not None:
        headline += f", {'up' if c >= 0 else 'down'} {abs(c):.1f}% on the month before"
    if (y := _change(m["revenue"], year, "revenue")) is not None:
        headline += f" and {'up' if y >= 0 else 'down'} {abs(y):.1f}% on a year earlier"
    headline += f", from {_number(m['orders'])} orders."

    charts: list[ReportChart] = []
    rankings: dict[str, list[tuple[str, str, str]]] = {}

    # Daily revenue across the month (days without sales count as 0).
    days = pd.date_range(period.start_time, period.end_time.normalize(), freq="D")
    daily = cur.groupby(cur["date"].dt.normalize())["revenue"].sum().reindex(days, fill_value=0)
    best_day = daily.idxmax()
    charts.append(
        ReportChart(
            "Revenue by day",
            f"Best day: {best_day:%a %d %b} with {fmt_money(float(daily.max()), currency)}; "
            f"average {fmt_money(float(daily.mean()), currency)} a day.",
            ChartSpec(
                kind="line",
                payload=jsonable(
                    {
                        "x": [d.date().isoformat() for d in days],
                        "x_is_date": True,
                        "series": [
                            {"name": "Revenue", "y": daily.round(2).tolist(), "role": "actual"}
                        ],
                        "markers": "points" if len(days) <= 31 else None,
                        "y_format": "money",
                    }
                ),
            ),
        )
    )

    # The last 12 months, with the report month highlighted.
    monthly = df.groupby(df["date"].dt.to_period("M"))["revenue"].sum()
    monthly = monthly[monthly.index <= period].tail(MONTHS_SHOWN)
    if len(monthly) >= 2:
        idx = list(monthly.index).index(period)
        rank = int((monthly > monthly[period]).sum()) + 1
        charts.append(
            ReportChart(
                "Last 12 months",
                f"{label} ranks #{rank} of the {len(monthly)} months shown.",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            # Every other month (and always this one), so labels don't collide.
                            "labels": [
                                p.strftime("%b") if (len(monthly) - 1 - i) % 2 == 0 else ""
                                for i, p in enumerate(monthly.index)
                            ],
                            "values": monthly.round(2).tolist(),
                            "highlight": [idx],
                            "value_format": "money",
                            "horizontal": False,
                        }
                    ),
                ),
            )
        )

    for col, title in (("product", "Top products"), ("region", "Top locations")):
        if not has(cur, col) or cur[col].nunique() < 2:
            continue
        top, rows = _ranking(cur, col, currency)
        rankings[title] = rows
        charts.append(
            ReportChart(
                title,
                f"{rows[0][0]} led with {rows[0][1]} ({rows[0][2]} of the month).",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            "labels": [str(k) for k in top.index],
                            "values": top.round(2).tolist(),
                            "highlight": [0],
                            "value_format": "money",
                        }
                    ),
                ),
            )
        )

    by_day = cur.groupby(cur["date"].dt.dayofweek)["revenue"].sum().reindex(range(7), fill_value=0)
    if (by_day > 0).sum() >= 3:
        best = int(by_day.idxmax())
        charts.append(
            ReportChart(
                "Sales by weekday",
                f"{WEEKDAYS[best]} was the strongest day of the week this month.",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            "labels": WEEKDAYS,
                            "values": by_day.round(2).tolist(),
                            "highlight": [best],
                            "value_format": "money",
                            "horizontal": False,
                        }
                    ),
                ),
            )
        )

    orders = _orders(cur)
    if len(orders) >= 10:
        clip = orders[orders <= orders.quantile(0.99)]  # keep rare huge orders off the axis
        charts.append(
            ReportChart(
                "Order size distribution",
                f"Half of all orders were under {fmt_money(float(orders.median()), currency)}.",
                ChartSpec(
                    kind="distribution",
                    payload=jsonable(
                        {
                            "values": clip.round(2).tolist(),
                            "value_format": "money",
                            "label": "Order value",
                        }
                    ),
                ),
            )
        )

    customers = None
    if has(df, "customer") and has(cur, "customer"):
        first_seen = df.groupby("customer")["date"].min().dt.to_period("M")
        active = cur["customer"].dropna().unique()
        new = [c for c in active if first_seen.get(c) == period]
        new_rev = float(cur[cur["customer"].isin(new)]["revenue"].sum())
        total = m["revenue"] or 1.0
        customers = {
            "Active customers": _number(len(active)),
            "New this month": _number(len(new)),
            "Returning": _number(len(active) - len(new)),
            "Revenue from new customers": f"{new_rev / total * 100:.0f}%",
        }

    stats = orders.describe(percentiles=[0.25, 0.5, 0.75])
    revenue_stats = [
        ("Orders", _number(float(stats["count"]))),
        ("Average", fmt_money(float(stats["mean"]), currency)),
        ("Median", fmt_money(float(stats["50%"]), currency)),
        ("Spread (std. dev.)", fmt_money(float(stats.get("std", 0) or 0), currency)),
        ("Smallest", fmt_money(float(stats["min"]), currency)),
        ("25% of orders below", fmt_money(float(stats["25%"]), currency)),
        ("75% of orders below", fmt_money(float(stats["75%"]), currency)),
        ("Largest", fmt_money(float(stats["max"]), currency)),
    ]

    cleaning = cleaning or {}
    eda = {
        "rows": int((profile or {}).get("row_count") or cleaning.get("rows_in") or len(df)),
        "columns": int((profile or {}).get("column_count") or 0),
        "rows_used": int(cleaning.get("rows_out") or len(df)),
        "date_range": f"{df['date'].min():%d %b %Y} to {df['date'].max():%d %b %Y}",
        "history_days": int(cleaning.get("history_days") or 0),
        "duplicates_removed": int(cleaning.get("duplicates_removed") or 0),
        "rows_dropped": int(cleaning.get("missing_date_dropped") or 0)
        + int(cleaning.get("missing_revenue_dropped") or 0),
        "quality_score": (quality or {}).get("score"),
        "quality_label": (quality or {}).get("label"),
        "issues": [i.get("message", "") for i in (quality or {}).get("issues", [])][:6],
        "column_table": [
            (
                c.get("name", ""),
                c.get("kind", ""),
                f"{float(c.get('missing_pct') or 0):.1f}%",
                _number(float(c.get("unique_count") or 0)),
            )
            for c in (profile or {}).get("columns", [])[:MAX_COLUMNS_LISTED]
        ],
        "columns_not_listed": max(0, len((profile or {}).get("columns", [])) - MAX_COLUMNS_LISTED),
    }

    return MonthlyReport(
        dataset_name=dataset_name,
        month=str(period),
        month_label=label,
        first_day=f"{cur['date'].min():%d %b %Y}",
        last_day=f"{cur['date'].max():%d %b %Y}",
        currency=currency,
        headline=headline,
        kpis=kpis,
        charts=charts,
        rankings=rankings,
        customers=customers,
        revenue_stats=revenue_stats,
        eda=eda,
        insights=[i for i in (insights or []) if i.kind != "kpi_summary"][:6],
        actions=actions or [],
        forecast=forecast,
        forecast_chart=forecast_chart,
    )
