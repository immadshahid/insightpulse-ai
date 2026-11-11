"""Pakistan holiday calendar for forecasting (Prophet holidays + model features)."""

from __future__ import annotations

from functools import lru_cache

import holidays
import pandas as pd

# Shopping builds up before the Eids; Prophet windows are in days relative to the date.
_WINDOWS: dict[str, tuple[int, int]] = {
    "Eid-ul-Fitr": (-14, 2),
    "Eid-ul-Adha": (-10, 2),
}


def _group(name: str) -> str:
    for key in _WINDOWS:
        if key in name:
            return key
    return "Public holiday"


@lru_cache
def pakistan_holidays(start_year: int, end_year: int) -> pd.DataFrame:
    """Prophet-style holidays frame: ``holiday, ds, lower_window, upper_window``."""
    cal = holidays.Pakistan(years=range(start_year, end_year + 1))
    rows = []
    for day, name in sorted(cal.items()):
        group = _group(name)
        lower, upper = _WINDOWS.get(group, (0, 0))
        rows.append(
            {
                "holiday": group,
                "ds": pd.Timestamp(day),
                "lower_window": lower,
                "upper_window": upper,
            }
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["holiday", "ds"]).reset_index(drop=True)


def eid_proximity(dates: pd.DatetimeIndex) -> pd.Series:
    """0..1 feature that rises over the 14 days before each Eid (for tree models)."""
    frame = pakistan_holidays(dates.min().year, dates.max().year + 1)
    eids = frame.loc[frame["holiday"].str.startswith("Eid"), "ds"].sort_values().to_numpy()
    out = []
    for d in dates.to_numpy():
        ahead = eids[eids >= d]
        days = (ahead[0] - d).astype("timedelta64[D]").astype(int) if len(ahead) else 999
        out.append(max(0.0, 1 - days / 14) if days <= 14 else 0.0)
    return pd.Series(out, index=dates)


def holiday_flag(dates: pd.DatetimeIndex) -> pd.Series:
    """1 on any Pakistani public holiday, else 0."""
    cal = holidays.Pakistan(years=range(dates.min().year, dates.max().year + 1))
    return pd.Series([1.0 if d.date() in cal else 0.0 for d in dates], index=dates)
