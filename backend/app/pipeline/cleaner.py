"""Clean a raw table into the canonical analysis frame.

Canonical columns: ``date`` (datetime), ``revenue`` (float) and, when mapped,
``quantity``, ``product``, ``customer``, ``region``, ``order_id``. Derived:
``month`` ("YYYY-MM"), ``weekday`` ("Mon".."Sun"), ``weekday_num`` (0-6) and
``hour`` (when the dates carry a time). Other numeric source columns are kept
under snake_case names for correlation analysis. Personal columns
(names, emails, phones) are never copied into the clean frame.
"""

from __future__ import annotations

import re

import pandas as pd
from pydantic import BaseModel

from app.pipeline.mapping import ColumnMapping
from app.pipeline.parsing import detect_currency, parse_dates, parse_numeric, parse_ratio

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_PII_HINTS = ("name", "email", "e-mail", "phone", "mobile", "contact", "address", "cnic")
_TEXT_ROLES = ("product", "customer", "region", "order_id")


class CleaningReport(BaseModel):
    """What the cleaner did, used for the data-quality score."""

    rows_in: int
    duplicates_removed: int
    missing_date_dropped: int
    missing_revenue_dropped: int
    negative_revenue_rows: int
    rows_out: int
    has_time: bool
    currency: str | None
    date_min: str | None
    date_max: str | None
    history_days: int
    missing_pct_by_role: dict[str, float]
    extra_numeric_columns: list[str]


def snake(name: str) -> str:
    """Convert a column name to snake_case ASCII."""
    s = re.sub(r"%", " pct", name)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s or "col"


def is_pii_column(name: str) -> bool:
    """True when a column name looks like personal data."""
    lowered = name.lower()
    return any(h in lowered for h in _PII_HINTS)


def clean(raw: pd.DataFrame, mapping: ColumnMapping) -> tuple[pd.DataFrame, CleaningReport]:
    """Return the cleaned canonical frame and a report of what changed."""
    roles = mapping.assigned()
    rows_in = len(raw)
    deduped = raw.drop_duplicates()
    duplicates_removed = rows_in - len(deduped)

    out = pd.DataFrame(index=deduped.index)
    out["date"] = parse_dates(deduped[roles["date"]])
    out["revenue"] = parse_numeric(deduped[roles["revenue"]])
    if "quantity" in roles:
        out["quantity"] = parse_numeric(deduped[roles["quantity"]])
    for role in _TEXT_ROLES:
        if role in roles:
            col = deduped[roles[role]].astype("string").str.strip()
            out[role] = col.where(col.str.len() > 0)

    missing_pct_by_role = {
        role: round(float(out[role].isna().mean() * 100), 2) for role in roles if role in out
    }

    extra_cols = _extra_numeric_columns(deduped, roles, set(out.columns))
    for src, dst in extra_cols.items():
        out[dst] = parse_numeric(deduped[src])

    no_date = out["date"].isna()
    no_revenue = out["revenue"].isna() & ~no_date
    out = out[~no_date & ~out["revenue"].isna()].copy()

    out = out.sort_values("date", kind="stable").reset_index(drop=True)
    has_time = bool(len(out)) and bool(
        (out["date"].dt.hour + out["date"].dt.minute > 0).mean() > 0.2
    )
    out["month"] = out["date"].dt.strftime("%Y-%m")
    out["weekday_num"] = out["date"].dt.weekday.astype("int64")
    out["weekday"] = out["weekday_num"].map(dict(enumerate(WEEKDAYS)))
    if has_time:
        out["hour"] = out["date"].dt.hour.astype("int64")

    date_min = out["date"].min() if len(out) else None
    date_max = out["date"].max() if len(out) else None
    report = CleaningReport(
        rows_in=rows_in,
        duplicates_removed=duplicates_removed,
        missing_date_dropped=int(no_date.sum()),
        missing_revenue_dropped=int(no_revenue.sum()),
        negative_revenue_rows=int((out["revenue"] < 0).sum()),
        rows_out=len(out),
        has_time=has_time,
        currency=detect_currency(raw[roles["revenue"]]),
        date_min=date_min.date().isoformat() if date_min is not None else None,
        date_max=date_max.date().isoformat() if date_max is not None else None,
        history_days=int((date_max - date_min).days) + 1 if date_min is not None else 0,
        missing_pct_by_role=missing_pct_by_role,
        extra_numeric_columns=list(extra_cols.values()),
    )
    return out, report


def _extra_numeric_columns(
    df: pd.DataFrame, roles: dict[str, str], taken: set[str]
) -> dict[str, str]:
    """Map other mostly-numeric, non-PII source columns to unique snake_case names."""
    used_sources = set(roles.values())
    result: dict[str, str] = {}
    for col in df.columns:
        if col in used_sources or is_pii_column(col) or "id" in snake(col).split("_"):
            continue
        if parse_ratio(df[col], "numeric") < 0.95:
            continue
        name = snake(col)
        while name in taken:
            name += "_x"
        taken.add(name)
        result[col] = name
    return result
