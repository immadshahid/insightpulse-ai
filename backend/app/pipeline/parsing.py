"""Shared value-parsing helpers (numbers with currency symbols, dates)."""

from __future__ import annotations

import re
import warnings

import pandas as pd

_CURRENCY_HINTS = {
    "PKR": ("rs", "pkr", "₨"),
    "USD": ("$", "usd"),
    "EUR": ("€", "eur"),
    "GBP": ("£", "gbp"),
    "INR": ("₹", "inr"),
    "AED": ("aed",),
}
_NON_NUMERIC = re.compile(r"[^0-9.\-]")
# A "numeric-looking" value: optional currency token, digits with separators, optional %.
_NUMERIC_LIKE = re.compile(
    r"^\(?\s*(?:rs\.?|pkr|usd|eur|gbp|inr|aed|[$€£₹₨])?\s*[-+]?\s*"
    r"(?:\d{1,3}(?:[,\s]\d{3})+|\d+)?(?:\.\d+)?\s*(?:rs\.?|pkr|usd|%)?\s*\)?$",
    re.IGNORECASE,
)


def looks_numeric(series: pd.Series) -> pd.Series:
    """Boolean mask: which values look like plain numbers/amounts (not IDs like 'ORD-12')."""
    s = series.astype("string").str.strip()
    return s.str.match(_NUMERIC_LIKE, na=False) & s.str.contains(r"\d", na=False)


def parse_numeric(series: pd.Series) -> pd.Series:
    """Coerce a column to float, stripping currency symbols, commas, % and spaces.

    Accounting negatives like ``(1,200)`` become ``-1200``. Unparseable values are NaN.
    """
    if pd.api.types.is_numeric_dtype(series):
        return series.astype("float64")
    s = series.astype("string").str.strip()
    negative = s.str.match(r"^\(.*\)$", na=False)
    cleaned = s.str.replace(_NON_NUMERIC, "", regex=True)
    cleaned = cleaned.where(cleaned.str.len() > 0)
    out = pd.to_numeric(cleaned, errors="coerce").astype("float64")
    return out.where(~negative, -out.abs())


def detect_currency(series: pd.Series) -> str | None:
    """Guess an ISO currency code from symbols in a text column, if any."""
    if pd.api.types.is_numeric_dtype(series):
        return None
    sample = " ".join(series.dropna().astype(str).head(500)).lower()
    for code, hints in _CURRENCY_HINTS.items():
        if any(h in sample for h in hints):
            return code
    return None


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a column to datetimes, choosing day-first if that parses more values."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.tz_localize(None) if series.dt.tz is not None else series
    if pd.api.types.is_numeric_dtype(series):
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    s = series.astype("string").str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a = pd.to_datetime(s, errors="coerce", format="mixed")
        if a.notna().mean() >= 0.98:
            return a
        b = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=True)
    return b if b.notna().sum() > a.notna().sum() else a


def parse_ratio(series: pd.Series, kind: str) -> float:
    """Share of non-null values that parse as ``kind`` ('numeric' or 'date')."""
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    sample = non_null.head(500)
    if kind == "numeric":
        if pd.api.types.is_numeric_dtype(sample):
            return 1.0
        return float(looks_numeric(sample).mean())
    return float(parse_dates(sample).notna().mean())
