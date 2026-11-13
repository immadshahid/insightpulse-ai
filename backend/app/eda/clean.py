"""Light cleaning for general tables: typed columns, empty rows and columns removed;
exact duplicate rows are counted but kept.

Column names are kept as the user wrote them (trimmed), because people recognise them.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.pipeline.parsing import parse_dates, parse_numeric
from app.pipeline.profiler import DatasetProfile


def clean_general(
    raw: pd.DataFrame, profile: DatasetProfile
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Typed copy of ``raw`` plus a short report of what was changed."""
    df = raw.copy()
    df.columns = [str(c).strip() or f"Column {i + 1}" for i, c in enumerate(df.columns)]
    kinds = {str(c.name).strip(): c.kind for c in profile.columns}
    for col in df.columns:
        kind = kinds.get(col)
        if kind == "numeric" and not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = parse_numeric(df[col])
        elif kind == "datetime" and not pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = parse_dates(df[col])
        elif kind in ("categorical", "text", "identifier") and df[col].dtype == object:
            df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
            df[col] = df[col].replace("", None)
    rows_in = len(df)
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    df = df.drop(columns=empty_cols).dropna(how="all")
    df = df.reset_index(drop=True)
    report = {
        "rows_in": rows_in,
        "rows_out": len(df),
        "empty_rows_dropped": rows_in - len(df),
        # Kept: in general data, identical rows can be different records (two passengers
        # with the same details), so they are only reported.
        "duplicate_rows": int(df.duplicated().sum()),
        "empty_columns_dropped": empty_cols,
        "history_days": 0,
    }
    return df, report
