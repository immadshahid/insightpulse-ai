"""Shared types and helpers for the insight library."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

Category = Literal[
    "sales",
    "products",
    "customers",
    "anomalies",
    # General (non-sales) datasets
    "target",
    "quality",
    "relationships",
    "distributions",
]
ChartKind = Literal[
    "line", "bar_ranking", "heatmap", "distribution", "corr_heatmap", "scatter_reg", "donut", "shap"
]


class ChartSpec(BaseModel):
    """A renderable chart: a builder name plus a JSON-safe data payload."""

    kind: ChartKind
    payload: dict[str, Any]


class Insight(BaseModel):
    """One scored finding. ``data`` is the only thing an LLM narrative may use (Phase 3)."""

    id: str
    kind: str
    category: Category
    tag: str
    headline: str
    why_it_matters: str
    score: float = Field(ge=0, le=1)
    data: dict[str, Any]
    chart: ChartSpec | None = None
    narrative: str | None = None


@dataclass(frozen=True)
class InsightContext:
    """Facts about the dataset that analyses need besides the frame itself."""

    currency: str | None = None
    has_time: bool = False

    @classmethod
    def from_frame(cls, df: pd.DataFrame, currency: str | None = None) -> InsightContext:
        """Build a context from a clean frame."""
        return cls(currency=currency, has_time="hour" in df.columns)


def has(df: pd.DataFrame, *cols: str) -> bool:
    """True when every column exists and has at least one non-null value."""
    return all(c in df.columns and df[c].notna().any() for c in cols)


def order_count(df: pd.DataFrame) -> int:
    """Distinct orders when an order id exists, otherwise row count."""
    if has(df, "order_id"):
        return int(df["order_id"].nunique())
    return int(len(df))


def pct_change(current: float, previous: float) -> float | None:
    """Percentage change, or None when the base is zero/missing."""
    if previous is None or previous == 0 or math.isnan(previous):
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def compact_number(value: float) -> str:
    """1234567 -> '1.2M', 45300 -> '45.3K'."""
    a = abs(value)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value / div:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{value:,.0f}" if a >= 100 else f"{value:,.2f}".rstrip("0").rstrip(".")


def fmt_money(value: float, currency: str | None) -> str:
    """Compact money string with an optional currency code."""
    text = compact_number(value)
    return f"{currency} {text}" if currency else text


def fmt_change(change: float | None, base_label: str) -> str:
    """'up 8.2% on Sep' / 'down 3.0% on Sep' / ''."""
    if change is None:
        return ""
    direction = "up" if change >= 0 else "down"
    return f"{direction} {abs(change):.1f}% on {base_label}"


def jsonable(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars and NaN to JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def clamp01(x: float) -> float:
    """Clamp a score into [0, 1]."""
    return float(max(0.0, min(1.0, x)))


def complete_months(df: pd.DataFrame) -> pd.Series:
    """Monthly revenue, dropping a trailing month that is less than ~80% elapsed."""
    monthly = df.groupby("month")["revenue"].sum().sort_index()
    if monthly.empty:
        return monthly
    last = df["date"].max()
    days_in_month = last.days_in_month
    if last.day < days_in_month * 0.8 and len(monthly) > 1:
        monthly = monthly.iloc[:-1]
    first = df["date"].min()
    if first.day > 5 and len(monthly) > 2:  # partial first month
        monthly = monthly.iloc[1:]
    return monthly


def month_label(month: str) -> str:
    """'2026-10' -> 'Oct 2026'."""
    return pd.Timestamp(month + "-01").strftime("%b %Y")


def weekly_totals(s: pd.Series | pd.DataFrame, anchor: str = "end") -> pd.Series | pd.DataFrame:
    """Sum a daily series into 7-day blocks labelled by each block's last day.

    ``anchor="end"`` counts blocks back from the last day (history: the final point is
    the last actual day); ``anchor="start"`` counts forward from the first day
    (forecasts). Incomplete blocks at the far end are dropped.
    """
    idx = s.index
    k = (idx.max() - idx).days // 7 if anchor == "end" else (idx - idx.min()).days // 7
    k = pd.Index(k)
    grouped = s.groupby(k.to_numpy())
    sizes = grouped.size()
    totals = grouped.sum()[sizes == 7]
    labels = pd.Series(idx, index=k).groupby(level=0).max()
    totals.index = pd.DatetimeIndex(labels.loc[totals.index].to_numpy())
    return totals.sort_index()
