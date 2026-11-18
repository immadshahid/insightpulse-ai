"""Combine two or more uploaded tables into one.

* **Stack**: files with the same columns (January, February, March exports) are placed
  under each other, with a "Source file" column so the files can still be compared.
* **Join**: related files (orders + customers + products) are linked on a shared key
  column that is found automatically; each lookup file adds its columns to the main one.

Everything here works on plain DataFrames; the dataset service stores the result as a
new dataset, so dashboards, Explore, Predict and Ask AI work on it unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

MAX_COMBINED_ROWS = 300_000
MAX_TABLES = 6
SOURCE_COLUMN = "Source file"
MIN_SHARED_FOR_STACK = 0.6  # share of each file's columns that every file must have
MIN_MATCH = 0.5  # share of main-file rows that must find a partner row
DETECT_SAMPLE = 20_000
GENERIC_KEYS = {"id", "index", "rowid", "no", "sno", "srno", "number", "code", "key"}


class CombineError(ValueError):
    """The tables can't be combined that way (message is shown to the user)."""


@dataclass
class Table:
    """One uploaded table and the name the user knows it by."""

    name: str
    df: pd.DataFrame


@dataclass
class JoinStep:
    """One lookup file linked to the main table."""

    left: str
    right: str
    left_column: str
    right_column: str
    match_pct: float
    columns_added: int


@dataclass
class StackPlan:
    """Whether and how the files can be stacked."""

    possible: bool
    rows: int = 0
    columns: int = 0
    shared_columns: list[str] = field(default_factory=list)
    partial_columns: list[str] = field(default_factory=list)  # missing from some files
    reason: str | None = None


@dataclass
class JoinPlan:
    """Whether and how the files can be joined."""

    possible: bool
    base: str | None = None
    rows: int = 0
    columns: int = 0
    steps: list[JoinStep] = field(default_factory=list)
    reason: str | None = None


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _tokens(name: Any) -> set[str]:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))
    return {t for t in re.split(r"[^a-z0-9]+", spaced.lower()) if t}


def _check(tables: list[Table]) -> None:
    if len(tables) < 2:
        raise CombineError("Choose at least two datasets to combine.")
    if len(tables) > MAX_TABLES:
        raise CombineError(f"Combine up to {MAX_TABLES} datasets at a time.")
    for t in tables:
        if t.df.empty or not len(t.df.columns):
            raise CombineError(f"{t.name} has no rows to combine.")


# ------------------------------------------------------------------ stack


def stack_plan(tables: list[Table]) -> StackPlan:
    """Can these files be placed under each other?"""
    per_table = [{_norm(c) for c in t.df.columns} for t in tables]
    common = set.intersection(*per_table)
    widest = max(len(cols) for cols in per_table)
    rows = sum(len(t.df) for t in tables)
    if not common or len(common) < MIN_SHARED_FOR_STACK * widest:
        return StackPlan(
            possible=False,
            reason="These files don't have the same columns, so they can't be stacked.",
        )
    if rows > MAX_COMBINED_ROWS:
        return StackPlan(
            possible=False,
            reason=f"Together these files have {rows:,} rows; the limit is "
            f"{MAX_COMBINED_ROWS:,}.",
        )
    canonical = _canonical_names(tables)
    return StackPlan(
        possible=True,
        rows=rows,
        columns=len(canonical) + 1,
        shared_columns=[name for key, name in canonical.items() if key in common],
        partial_columns=[name for key, name in canonical.items() if key not in common],
    )


def _canonical_names(tables: list[Table]) -> dict[str, str]:
    """Normalised name -> the first spelling seen, in first-seen order."""
    names: dict[str, str] = {}
    for t in tables:
        for col in t.df.columns:
            names.setdefault(_norm(col), str(col).strip())
    return names


def stack(tables: list[Table]) -> pd.DataFrame:
    """Place the files under each other, matching columns by name (ignoring case, spaces
    and punctuation), and record which file each row came from."""
    _check(tables)
    plan = stack_plan(tables)
    if not plan.possible:
        raise CombineError(plan.reason or "These files can't be stacked.")
    canonical = _canonical_names(tables)
    source = SOURCE_COLUMN
    while _norm(source) in canonical:
        source += " name"
    parts = []
    for t in tables:
        part = t.df.rename(columns={c: canonical[_norm(c)] for c in t.df.columns})
        part = part.loc[:, ~part.columns.duplicated()]
        part[source] = t.name
        parts.append(part)
    out = pd.concat(parts, ignore_index=True, sort=False)
    return out[[*canonical.values(), source]]


# ------------------------------------------------------------------ join


def _key(series: pd.Series) -> pd.Series:
    """Values as comparable text: '1042.0', ' 1042 ' and 1042 all become '1042'."""
    text = series.astype("string").str.strip().str.lower()
    text = text.str.replace(r"\.0+$", "", regex=True)
    return text.mask(text.isin(["", "nan", "none", "<na>"]))


def _mostly_text(keys: pd.Series) -> bool:
    present = keys.dropna()
    return bool(len(present)) and float(present.str.fullmatch(r"-?\d+(\.\d+)?").mean()) < 0.5


def _find_link(left: pd.DataFrame, right: pd.DataFrame) -> tuple[str, str, float] | None:
    """Best (left column, right column, share of left rows matched), where the right
    column identifies each right row exactly once (a lookup table)."""
    sample = left if len(left) <= DETECT_SAMPLE else left.sample(DETECT_SAMPLE, random_state=0)
    left_keys = {c: _key(sample[c]).dropna() for c in sample.columns}
    best: tuple[float, str, str, float] | None = None
    for rcol in right.columns:
        rkeys = _key(right[rcol])
        present = rkeys.dropna()
        if len(present) < 2 or len(present) < 0.9 * len(right) or present.duplicated().any():
            continue
        values = set(present)
        for lcol, lkeys in left_keys.items():
            if lkeys.empty:
                continue
            match = float(lkeys.isin(values).mean())
            if match < MIN_MATCH:
                continue
            same_name = _norm(lcol) == _norm(rcol)
            related = bool((_tokens(lcol) & _tokens(rcol)) - {"id", "no", "number", "code"})
            # Unrelated number columns often overlap by chance (1, 2, 3...), so they need
            # matching names; text keys such as emails or SKUs may match on values alone.
            if not (same_name or related or (match >= 0.8 and _mostly_text(lkeys))):
                continue
            score = match + (0.5 if same_name else 0.25 if related else 0.0)
            if _norm(rcol) in GENERIC_KEYS:
                score -= 0.4  # a bare "id" in both files is weaker evidence than customer_id
            if best is None or score > best[0]:
                best = (score, str(lcol), str(rcol), match)
    return (best[1], best[2], best[3]) if best else None


def _join_all(tables: list[Table]) -> tuple[pd.DataFrame | None, JoinPlan]:
    base = max(tables, key=lambda t: len(t.df))
    if len(base.df) > MAX_COMBINED_ROWS:
        return None, JoinPlan(
            possible=False,
            reason=f"{base.name} has {len(base.df):,} rows; the limit is {MAX_COMBINED_ROWS:,}.",
        )
    merged = base.df.copy()
    merged.columns = [str(c) for c in merged.columns]
    owner = {c: base.name for c in merged.columns}
    remaining = [t for t in tables if t is not base]
    steps: list[JoinStep] = []
    progress = True
    while remaining and progress:
        progress = False
        for t in list(remaining):
            link = _find_link(merged, t.df)
            if link is None:
                continue
            lcol, rcol, match = link
            right = t.df.copy()
            right.columns = [str(c) for c in right.columns]
            right["__key"] = _key(right[rcol])
            right = right.dropna(subset=["__key"]).drop_duplicates("__key")
            if _norm(lcol) == _norm(rcol):
                right = right.drop(columns=[rcol])  # the key is already in the main table
            taken = {_norm(c) for c in merged.columns}
            renames = {
                c: f"{c} ({t.name})" for c in right.columns if c != "__key" and _norm(c) in taken
            }
            right = right.rename(columns=renames)
            added = [c for c in right.columns if c != "__key"]
            merged["__key"] = _key(merged[lcol])
            merged = merged.merge(right, on="__key", how="left").drop(columns="__key")
            steps.append(
                JoinStep(
                    left=owner.get(lcol, base.name),
                    right=t.name,
                    left_column=lcol,
                    right_column=rcol,
                    match_pct=round(match * 100, 1),
                    columns_added=len(added),
                )
            )
            owner.update(dict.fromkeys(added, t.name))
            remaining.remove(t)
            progress = True
    if remaining:
        names = ", ".join(t.name for t in remaining)
        return None, JoinPlan(
            possible=False,
            base=base.name,
            steps=steps,
            reason=f"Couldn't find a column that links {names} to {base.name}. Linked files "
            "need a shared column, such as a customer or product ID, that appears once per "
            "row in the lookup file.",
        )
    plan = JoinPlan(
        possible=True, base=base.name, rows=len(merged), columns=len(merged.columns), steps=steps
    )
    return merged, plan


def join_plan(tables: list[Table]) -> JoinPlan:
    """Can these files be linked on shared key columns?"""
    return _join_all(tables)[1]


def join(tables: list[Table]) -> tuple[pd.DataFrame, JoinPlan]:
    """Add each lookup file's columns to the largest file, matched on the shared key."""
    _check(tables)
    merged, plan = _join_all(tables)
    if merged is None:
        raise CombineError(plan.reason or "These files can't be joined.")
    return merged, plan


# ------------------------------------------------------------------ both


def preview(tables: list[Table]) -> dict[str, Any]:
    """What each way of combining would produce, and which one fits these files."""
    _check(tables)
    s, j = stack_plan(tables), join_plan(tables)
    return {
        "suggested": "stack" if s.possible else "join" if j.possible else None,
        "stack": s,
        "join": j,
    }


def combine(tables: list[Table], mode: str) -> pd.DataFrame:
    """Combined table for ``mode`` ('stack' or 'join'); raises CombineError if impossible."""
    if mode == "stack":
        return stack(tables)
    if mode == "join":
        return join(tables)[0]
    raise CombineError("Choose 'stack' or 'join'.")
