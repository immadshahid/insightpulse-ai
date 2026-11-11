"""Period KPIs, revenue trend chart and summary text for the Home dashboard."""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel

from app.insights.base import (
    ChartSpec,
    Insight,
    fmt_change,
    fmt_money,
    has,
    jsonable,
    order_count,
    pct_change,
    weekly_totals,
)

Period = Literal["7d", "30d", "90d", "1y"]
PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
PERIOD_LABEL: dict[str, str] = {
    "7d": "last 7 days",
    "30d": "last 30 days",
    "90d": "last 90 days",
    "1y": "last 12 months",
}


class KpiCard(BaseModel):
    """One KPI tile: value, previous-period value and % change."""

    key: str
    label: str
    value: float
    display: str
    previous: float | None
    change_pct: float | None
    direction: Literal["up", "down", "flat"] | None
    # Small trend line for the tile: one value per day (7d/30d), week (90d) or
    # fortnight (1y) of the current period, oldest first.
    spark: list[float] = []


class PeriodWindow(BaseModel):
    """Current and previous date windows (inclusive), anchored on the data's last day."""

    start: str
    end: str
    prev_start: str
    prev_end: str
    # False when the data starts after the previous window begins, so a % change
    # would compare a full period with a partial one.
    previous_complete: bool = True


# The data may start a few days into the previous window and still count as complete.
PREV_GRACE = pd.Timedelta(days=3)


def split_period(df: pd.DataFrame, period: str) -> tuple[pd.DataFrame, pd.DataFrame, PeriodWindow]:
    """Slice ``df`` into the selected period and the equal-length period before it.

    The anchor is the last date in the data (not today), so historical uploads still
    show meaningful numbers.
    """
    days = PERIOD_DAYS[period]
    end = df["date"].max().normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=days)
    prev_start = start - pd.Timedelta(days=days)
    cur = df[(df["date"] >= start) & (df["date"] < end)]
    prev = df[(df["date"] >= prev_start) & (df["date"] < start)]
    window = PeriodWindow(
        start=start.date().isoformat(),
        end=(end - pd.Timedelta(days=1)).date().isoformat(),
        prev_start=prev_start.date().isoformat(),
        prev_end=(start - pd.Timedelta(days=1)).date().isoformat(),
        previous_complete=bool(df["date"].min().normalize() <= prev_start + PREV_GRACE),
    )
    return cur, prev, window


def _card(
    key: str, label: str, cur: float, prev: float | None, display: str, has_prev: bool
) -> KpiCard:
    change = pct_change(cur, prev) if has_prev and prev is not None else None
    direction = (
        None
        if change is None
        else ("flat" if abs(change) < 0.5 else "up" if change > 0 else "down")
    )
    return KpiCard(
        key=key,
        label=label,
        value=round(cur, 2),
        previous=round(prev, 2) if has_prev and prev is not None else None,
        change_pct=change,
        direction=direction,
        display=display,
    )


def kpi_cards(
    cur: pd.DataFrame, prev: pd.DataFrame, currency: str | None, comparable: bool = True
) -> list[KpiCard]:
    """Revenue, Orders, Avg order value and Active customers with % change.

    With ``comparable=False`` (the previous window is only partly covered by data) no
    previous values or % changes are reported, rather than misleading ones.
    """
    has_prev = comparable and len(prev) > 0
    rev, prev_rev = float(cur["revenue"].sum()), float(prev["revenue"].sum())
    orders, prev_orders = order_count(cur), order_count(prev)
    aov = rev / orders if orders else 0.0
    prev_aov = prev_rev / prev_orders if prev_orders else None
    cards = [
        _card("revenue", "Revenue", rev, prev_rev, fmt_money(rev, currency), has_prev),
        _card("orders", "Orders", orders, prev_orders, f"{orders:,}", has_prev),
        _card(
            "avg_order_value", "Avg order value", aov, prev_aov, fmt_money(aov, currency), has_prev
        ),
    ]
    if has(cur, "customer") or has(prev, "customer"):
        cust = int(cur["customer"].nunique()) if len(cur) else 0
        prev_cust = int(prev["customer"].nunique()) if has_prev else None
        cards.append(
            _card("active_customers", "Active customers", cust, prev_cust, f"{cust:,}", has_prev)
        )
    return cards


SPARK_STEP_DAYS = {"7d": 1, "30d": 1, "90d": 7, "1y": 14}


def kpi_sparklines(cur: pd.DataFrame, window: PeriodWindow, period: str) -> dict[str, list[float]]:
    """Per-bucket series for each KPI over the current period (empty buckets are 0)."""
    if cur.empty:
        return {}
    step = SPARK_STEP_DAYS[period]
    start = pd.Timestamp(window.start)
    n = PERIOD_DAYS[period] // step
    bucket = ((cur["date"].dt.normalize() - start).dt.days // step).clip(0, n - 1)
    g = cur.groupby(bucket)
    idx = range(n)
    revenue = g["revenue"].sum().reindex(idx, fill_value=0.0)
    orders = (g["order_id"].nunique() if has(cur, "order_id") else g.size()).reindex(
        idx, fill_value=0
    )
    aov = (revenue / orders.replace(0, pd.NA)).fillna(0.0)
    out = {
        "revenue": revenue.astype(float).round(2).tolist(),
        "orders": orders.astype(float).tolist(),
        "avg_order_value": aov.astype(float).round(2).tolist(),
    }
    if has(cur, "customer"):
        out["active_customers"] = (
            g["customer"].nunique().reindex(idx, fill_value=0).astype(float).tolist()
        )
    return out


def revenue_trend_chart(
    df: pd.DataFrame,
    cur: pd.DataFrame,
    period: str,
    currency: str | None,
    forecast: dict | None = None,
) -> ChartSpec | None:
    """Actual revenue over the period (daily up to 90 days, weekly for 1 year).

    When a revenue ``forecast`` result is available (``dates``, ``yhat``, ``lower``,
    ``upper``), the next ``min(period, horizon)`` days are added as a dashed line with
    its 80% band, starting from the last actual point, plus a 'Today' marker.
    """
    if cur.empty:
        return None
    weekly = period == "1y"
    daily = cur.set_index("date")["revenue"].resample("D").sum()
    series = weekly_totals(daily, anchor="end") if weekly else daily
    payload: dict = {
        "x": [d.strftime("%Y-%m-%d") for d in series.index],
        "x_is_date": True,
        "series": [{"name": "Actual", "y": series.tolist(), "role": "actual"}],
        "y_format": "money",
        "currency": currency,
        "markers": "points" if len(series) <= 14 else None,
    }
    if forecast and forecast.get("dates"):
        fc = pd.DataFrame(
            {k: forecast[k] for k in ("yhat", "lower", "upper")},
            index=pd.to_datetime(forecast["dates"]),
        ).iloc[: PERIOD_DAYS[period]]
        if weekly:
            fc = weekly_totals(fc, anchor="start")
        start_x, start_y = series.index[-1].strftime("%Y-%m-%d"), float(series.iloc[-1])
        fx = [start_x, *[d.strftime("%Y-%m-%d") for d in fc.index]]
        payload["series"].append(
            {"name": "Forecast", "x": fx, "y": [start_y, *fc["yhat"].tolist()], "role": "forecast"}
        )
        payload["band"] = {
            "x": fx,
            "lower": [start_y, *fc["lower"].tolist()],
            "upper": [start_y, *fc["upper"].tolist()],
            "label": "Likely range",
            "role": "forecast",
        }
        payload["today"] = start_x
        payload["markers"] = None
    return ChartSpec(kind="line", payload=jsonable(payload))


def summary_text(cards: list[KpiCard], period: str, top: Insight | None) -> str:
    """Template summary used until the Phase 3 LLM narrative replaces it."""
    by_key = {c.key: c for c in cards}
    rev = by_key["revenue"]
    text = f"Revenue was {rev.display} over the {PERIOD_LABEL[period]}"
    change = fmt_change(rev.change_pct, "the period before")
    text += f", {change}." if change else "."
    if top is not None:
        text += f" {top.headline}."
    return text
