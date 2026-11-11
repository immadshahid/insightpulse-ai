"""Column profiling: infer a kind for each column and summarise it."""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel

from app.pipeline.parsing import parse_numeric, parse_ratio

ColumnKind = Literal["datetime", "numeric", "categorical", "text", "identifier"]


class ColumnProfile(BaseModel):
    """Summary of a single column."""

    name: str
    kind: ColumnKind
    missing_pct: float
    unique_count: int
    sample_values: list[str]
    min: float | None = None
    max: float | None = None
    mean: float | None = None


class DatasetProfile(BaseModel):
    """Summary of a whole uploaded table."""

    row_count: int
    column_count: int
    columns: list[ColumnProfile]

    def column_names(self) -> list[str]:
        """Names of all profiled columns, in file order."""
        return [c.name for c in self.columns]


def infer_kind(series: pd.Series) -> ColumnKind:
    """Infer a coarse semantic kind for a column."""
    non_null = series.dropna()
    if non_null.empty:
        return "text"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    n = len(non_null)
    uniq_ratio = non_null.nunique() / n
    if pd.api.types.is_numeric_dtype(series):
        if uniq_ratio > 0.98 and pd.api.types.is_integer_dtype(series) and n > 50:
            return "identifier"
        return "numeric"
    if parse_ratio(series, "date") >= 0.9 and non_null.astype(str).str.len().median() >= 6:
        return "datetime"
    if parse_ratio(series, "numeric") >= 0.9:
        return "numeric"
    if uniq_ratio > 0.9 and n > 50:
        return "identifier"
    if non_null.nunique() <= max(50, int(0.05 * n)):
        return "categorical"
    return "text"


def profile_column(series: pd.Series) -> ColumnProfile:
    """Build a :class:`ColumnProfile` for one column."""
    kind = infer_kind(series)
    non_null = series.dropna()
    profile = ColumnProfile(
        name=str(series.name),
        kind=kind,
        missing_pct=round(float(series.isna().mean() * 100), 2),
        unique_count=int(non_null.nunique()),
        sample_values=[str(v) for v in non_null.head(5).tolist()],
    )
    if kind == "numeric":
        values = parse_numeric(series).dropna()
        if not values.empty:
            profile.min = float(values.min())
            profile.max = float(values.max())
            profile.mean = round(float(values.mean()), 4)
    return profile


def profile_dataframe(df: pd.DataFrame) -> DatasetProfile:
    """Profile every column of ``df``."""
    return DatasetProfile(
        row_count=int(len(df)),
        column_count=int(len(df.columns)),
        columns=[profile_column(df[c]) for c in df.columns],
    )


def sample_rows(df: pd.DataFrame, n: int = 5) -> list[dict[str, str]]:
    """First ``n`` rows as string dicts (what the LLM mapper is allowed to see)."""
    head = df.head(n)
    return [
        {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        for row in head.to_dict(orient="records")
    ]
