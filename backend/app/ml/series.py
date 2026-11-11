"""Daily time series for forecastable metrics."""

from __future__ import annotations

import pandas as pd

from app.insights.base import has

TARGETS: dict[str, str] = {"revenue": "Revenue", "orders": "Orders", "quantity": "Units sold"}


class TargetError(ValueError):
    """The requested metric is not available in this dataset."""


def available_targets(df: pd.DataFrame) -> list[str]:
    """Targets this dataset can forecast."""
    out = ["revenue", "orders"]
    if has(df, "quantity"):
        out.append("quantity")
    return out


def daily_series(df: pd.DataFrame, target: str) -> pd.Series:
    """Daily totals for ``target`` with missing days filled with 0."""
    if target not in available_targets(df):
        raise TargetError(f"'{target}' can't be forecast for this dataset.")
    indexed = df.set_index("date")
    if target == "revenue":
        s = indexed["revenue"].resample("D").sum()
    elif target == "quantity":
        s = indexed["quantity"].resample("D").sum()
    else:
        key = "order_id" if has(df, "order_id") else None
        s = (
            indexed["order_id"].resample("D").nunique()
            if key
            else indexed["revenue"].resample("D").size()
        )
    s = s.asfreq("D", fill_value=0).astype("float64")
    s.name = target
    return s
