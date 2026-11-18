"""Data cleaning as a list of fixed, validated operations.

A plan is a list of steps such as "remove rows where Age is missing" or "merge 'lahore'
into 'Lahore'". Steps come from the app's own suggestions or from the AI turning a
sentence into steps (see :mod:`app.ai.cleaning`); either way only the operations defined
here can run. Nothing is executed as code. Plans are applied to a copy of the uploaded
table and saved as a new dataset, so the original is never changed.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.pipeline.parsing import parse_dates, parse_numeric

MAX_STEPS = 12
OPS = (
    "drop_missing",
    "fill_missing",
    "drop_columns",
    "rename_column",
    "remove_duplicates",
    "replace_values",
    "filter_rows",
    "change_case",
    "trim_text",
    "remove_outliers",
    "convert_type",
)
FILL_METHODS = ("median", "mean", "mode", "value", "zero")
COMPARISONS = ("eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_contains")
CASES = ("lower", "upper", "title")
TYPES = ("number", "date", "text")
_COMPARE_WORDS = {
    "eq": "is",
    "neq": "is not",
    "gt": "is greater than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "contains": "contains",
    "not_contains": "does not contain",
}


class CleanError(ValueError):
    """The plan can't be run as asked (message is shown to the user)."""


@dataclass
class Step:
    """One cleaning operation with its settings (unused settings stay empty)."""

    op: str
    column: str | None = None
    columns: list[str] = field(default_factory=list)
    method: str | None = None
    value: str | None = None
    new_name: str | None = None
    values: list[str] = field(default_factory=list)
    comparison: str | None = None
    keep: bool | None = None
    case: str | None = None
    to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON form, the same shape the API accepts."""
        return {
            "op": self.op,
            "column": self.column,
            "columns": self.columns,
            "method": self.method,
            "value": self.value,
            "new_name": self.new_name,
            "values": self.values,
            "comparison": self.comparison,
            "keep": self.keep,
            "case": self.case,
            "to": self.to,
        }


@dataclass
class StepResult:
    """What one step did, in plain words and in numbers."""

    step: Step
    description: str
    effect: str
    rows_removed: int = 0
    cells_changed: int = 0
    columns_removed: int = 0


@dataclass
class CleanPreview:
    """The whole plan's effect on the table."""

    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    steps: list[StepResult]


# ------------------------------------------------------------------ helpers


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _resolve(df: pd.DataFrame, name: str | None) -> str:
    """The real column for ``name`` (exact, else ignoring case, spaces and punctuation)."""
    if not name or not str(name).strip():
        raise CleanError("This step needs a column.")
    columns = [str(c) for c in df.columns]
    if name in columns:
        return name
    matches = [c for c in columns if _norm(c) == _norm(name)]
    if len(matches) == 1:
        return matches[0]
    shown = ", ".join(columns[:20]) + ("..." if len(columns) > 20 else "")
    raise CleanError(f"There is no column called '{name}'. Columns: {shown}.")


def _text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _is_text(series: pd.Series) -> bool:
    return not (
        pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series)
    )


def _number(value: Any) -> str:
    v = float(value)
    return f"{v:,.0f}" if v.is_integer() else f"{v:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _list(names: list[str]) -> str:
    return ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")


def _need(value: Any, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise CleanError(f"Choose {what}: {', '.join(allowed)}.")
    return str(value)


# ------------------------------------------------------------------ operations


def _drop_missing(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    cols = [_resolve(df, c) for c in s.columns] or ([_resolve(df, s.column)] if s.column else [])
    s.columns, s.column = cols, None
    mask = df[cols].isna().any(axis=1) if cols else df.isna().any(axis=1)
    where = f"{_list(cols)} is missing" if cols else "any value is missing"
    out = df[~mask]
    n = int(mask.sum())
    return out, StepResult(s, f"Remove rows where {where}", f"Removes {_plural(n, 'row')}", n)


def _fill_missing(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    method = s.method = _need(s.method, FILL_METHODS, "how to fill the gaps")
    series = df[col]
    missing = int(series.isna().sum())
    if method in ("median", "mean"):
        numbers = series if pd.api.types.is_numeric_dtype(series) else parse_numeric(series)
        if numbers.notna().sum() == 0:
            raise CleanError(f"{col} has no numbers, so it has no {method}. Use the mode instead.")
        fill: Any = round(float(numbers.median() if method == "median" else numbers.mean()), 4)
        shown = f"{_number(fill)} (the {method})"
    elif method == "mode":
        modes = series.dropna().mode()
        if modes.empty:
            raise CleanError(f"{col} is completely empty, so there is nothing to fill it with.")
        fill = modes.iloc[0]
        shown = f"'{fill}' (the most common value)"
    elif method == "zero":
        fill, shown = 0, "0"
    else:
        if s.value is None or not str(s.value).strip():
            raise CleanError("Say what value to put in the empty cells.")
        fill = s.value.strip()
        if pd.api.types.is_numeric_dtype(series):
            try:
                fill = float(fill)
            except ValueError as exc:
                raise CleanError(f"{col} holds numbers, so '{s.value}' doesn't fit.") from exc
        shown = f"'{s.value.strip()}'"
    out = df.copy()
    out[col] = series.fillna(fill)
    return out, StepResult(
        s,
        f"Fill empty cells in {col} with {shown}",
        f"Fills {_plural(missing, 'empty cell')}",
        cells_changed=missing,
    )


def _drop_columns(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    cols = [_resolve(df, c) for c in s.columns] or ([_resolve(df, s.column)] if s.column else [])
    if not cols:
        raise CleanError("Say which column to remove.")
    s.columns, s.column = cols, None
    if len(cols) >= len(df.columns):
        raise CleanError("That would remove every column.")
    return df.drop(columns=cols), StepResult(
        s,
        f"Remove the column{'' if len(cols) == 1 else 's'} {_list(cols)}",
        f"Removes {_plural(len(cols), 'column')}",
        columns_removed=len(cols),
    )


def _rename_column(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    new = (s.new_name or "").strip()
    if not new:
        raise CleanError("Say what the new column name should be.")
    if any(_norm(c) == _norm(new) for c in df.columns if c != col):
        raise CleanError(f"There is already a column called '{new}'.")
    s.new_name = new[:120]
    return df.rename(columns={col: s.new_name}), StepResult(
        s, f"Rename {col} to {s.new_name}", "Renames 1 column"
    )


def _remove_duplicates(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    cols = s.columns = [_resolve(df, c) for c in s.columns]
    mask = df.duplicated(subset=cols or None)
    n = int(mask.sum())
    what = f"rows that repeat the same {_list(cols)}" if cols else "rows that are exact copies"
    return df[~mask], StepResult(
        s, f"Remove {what}", f"Removes {_plural(n, 'row')} (the first of each is kept)", n
    )


def _replace_values(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    old = [str(v).strip() for v in s.values if str(v).strip()]
    if not old:
        raise CleanError("Say which values to replace.")
    if s.value is None:
        raise CleanError("Say what to replace them with.")
    new = s.value.strip()
    s.values, s.value = old, new
    text = _text(df[col])
    wanted = {v.lower() for v in old}
    mask = text.str.lower().isin(wanted) & (df[col].astype("string") != new)
    n = int(mask.fillna(False).sum())
    out = df.copy()
    replacement: Any = new
    if pd.api.types.is_numeric_dtype(df[col]):
        try:
            replacement = float(new)
        except ValueError:
            out[col] = out[col].astype("object")
    out.loc[mask.fillna(False), col] = replacement
    quoted = ", ".join(f"'{v}'" for v in old[:4]) + ("..." if len(old) > 4 else "")
    return out, StepResult(
        s,
        f"In {col}, change {quoted} to '{new}'",
        f"Changes {_plural(n, 'cell')}",
        cells_changed=n,
    )


def _filter_rows(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    op = s.comparison = _need(s.comparison, COMPARISONS, "a comparison")
    if s.value is None or not str(s.value).strip():
        raise CleanError("Say what value to compare with.")
    raw = s.value = str(s.value).strip()
    keep = s.keep = bool(s.keep)
    series = df[col]
    if op in ("contains", "not_contains"):
        hit = _text(series).str.contains(raw, case=False, regex=False).fillna(False)
        mask = hit if op == "contains" else ~hit & series.notna()
    elif op in ("eq", "neq"):
        same = (_text(series).str.lower() == raw.lower()).fillna(False)
        if pd.api.types.is_numeric_dtype(series):
            with contextlib.suppress(ValueError):
                same = (series == float(raw)).fillna(False)
        mask = same if op == "eq" else ~same & series.notna()
    else:
        if pd.api.types.is_datetime64_any_dtype(series):
            target: Any = pd.Timestamp(raw)
            values = series
        else:
            values = series if pd.api.types.is_numeric_dtype(series) else parse_numeric(series)
            if values.notna().sum() == 0:
                dates = parse_dates(series)
                if dates.notna().sum() == 0:
                    raise CleanError(f"{col} isn't a number or a date, so it can't be compared.")
                values, target = dates, pd.Timestamp(raw)
            else:
                try:
                    target = float(raw.replace(",", ""))
                except ValueError as exc:
                    raise CleanError(f"'{raw}' isn't a number to compare {col} with.") from exc
        compare = {"gt": values > target, "gte": values >= target}
        compare |= {"lt": values < target, "lte": values <= target}
        mask = compare[op].fillna(False)
    removed = ~mask if keep else mask
    n = int(removed.sum())
    verb = "Keep only" if keep else "Remove"
    return df[~removed], StepResult(
        s,
        f"{verb} rows where {col} {_COMPARE_WORDS[op]} {raw}",
        f"Removes {_plural(n, 'row')}",
        n,
    )


def _change_case(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    case = s.case = _need(s.case, CASES, "a letter case")
    if not _is_text(df[col]):
        raise CleanError(f"{col} isn't text, so its letter case can't change.")
    text = _text(df[col])
    changed = getattr(text.str, case)()
    n = int((changed != df[col].astype("string")).fillna(False).sum())
    out = df.copy()
    out[col] = changed.astype("object").where(df[col].notna(), None)
    words = {"lower": "lower case", "upper": "UPPER CASE", "title": "Title Case"}
    return out, StepResult(
        s, f"Write {col} in {words[case]}", f"Changes {_plural(n, 'cell')}", cells_changed=n
    )


def _trim_text(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    cols = [_resolve(df, c) for c in s.columns] or ([_resolve(df, s.column)] if s.column else [])
    cols = cols or [str(c) for c in df.columns if _is_text(df[c])]
    s.columns, s.column = cols, None
    out, n = df.copy(), 0
    for col in cols:
        if not _is_text(df[col]):
            continue
        original = df[col].astype("string")
        tidy = original.str.strip().str.replace(r"\s+", " ", regex=True)
        n += int((tidy != original).fillna(False).sum())
        out[col] = tidy.astype("object").where(df[col].notna(), None)
    return out, StepResult(
        s,
        f"Remove extra spaces in {_list(cols) if len(cols) <= 5 else 'all text columns'}",
        f"Changes {_plural(n, 'cell')}",
        cells_changed=n,
    )


def _remove_outliers(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    values = df[col] if pd.api.types.is_numeric_dtype(df[col]) else parse_numeric(df[col])
    if values.notna().sum() < 8:
        raise CleanError(f"{col} doesn't have enough numbers to find unusual values.")
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    mask = ((values < low) | (values > high)).fillna(False)
    n = int(mask.sum())
    return df[~mask], StepResult(
        s,
        f"Remove rows where {col} is unusually low or high "
        f"(outside {_number(low)} to {_number(high)})",
        f"Removes {_plural(n, 'row')}",
        n,
    )


def _convert_type(df: pd.DataFrame, s: Step) -> tuple[pd.DataFrame, StepResult]:
    col = s.column = _resolve(df, s.column)
    to = s.to = _need(s.to, TYPES, "a type")
    out = df.copy()
    before = int(df[col].notna().sum())
    if to == "number":
        out[col] = df[col] if pd.api.types.is_numeric_dtype(df[col]) else parse_numeric(df[col])
    elif to == "date":
        out[col] = parse_dates(df[col])
    else:
        out[col] = df[col].astype("string").astype("object").where(df[col].notna(), None)
    lost = before - int(out[col].notna().sum())
    if before and lost == before:
        raise CleanError(f"None of the values in {col} can be read as a {to}.")
    note = f"; {_plural(lost, 'value')} that can't be read become empty" if lost else ""
    return out, StepResult(
        s, f"Treat {col} as a {to}", f"Converts {_plural(before - lost, 'value')}{note}"
    )


_RUN = {
    "drop_missing": _drop_missing,
    "fill_missing": _fill_missing,
    "drop_columns": _drop_columns,
    "rename_column": _rename_column,
    "remove_duplicates": _remove_duplicates,
    "replace_values": _replace_values,
    "filter_rows": _filter_rows,
    "change_case": _change_case,
    "trim_text": _trim_text,
    "remove_outliers": _remove_outliers,
    "convert_type": _convert_type,
}


# ------------------------------------------------------------------ plans


def parse_steps(raw: list[dict[str, Any]]) -> list[Step]:
    """Build steps from JSON; unknown operations are refused."""
    if not raw:
        raise CleanError("There is nothing to change yet.")
    if len(raw) > MAX_STEPS:
        raise CleanError(f"Apply up to {MAX_STEPS} changes at a time.")
    steps = []
    for item in raw:
        op = item.get("op")
        if op not in OPS:
            raise CleanError(f"'{op}' is not a cleaning step this app can do.")
        steps.append(
            Step(
                op=op,
                column=item.get("column") or None,
                columns=[str(c) for c in item.get("columns") or []],
                method=item.get("method") or None,
                value=None if item.get("value") is None else str(item["value"]),
                new_name=item.get("new_name") or None,
                values=[str(v) for v in item.get("values") or []],
                comparison=item.get("comparison") or None,
                keep=item.get("keep"),
                case=item.get("case") or None,
                to=item.get("to") or None,
            )
        )
    return steps


def apply_steps(df: pd.DataFrame, steps: list[Step]) -> tuple[pd.DataFrame, CleanPreview]:
    """Run the plan on a copy of ``df``. Raises CleanError with a plain explanation when a
    step doesn't fit the data or the plan would leave nothing."""
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    results: list[StepResult] = []
    for step in steps:
        out, result = _RUN[step.op](out, step)
        results.append(result)
        if out.empty:
            raise CleanError(f"'{result.description}' would remove every row.")
    out = out.reset_index(drop=True)
    return out, CleanPreview(len(df), len(out), len(df.columns), len(out.columns), results)


def keep_valid(df: pd.DataFrame, steps: list[Step]) -> tuple[list[Step], list[str]]:
    """The steps that fit this table, in order, and why each of the others was skipped.

    Used for typed requests, so one impossible part ("drop the notes column" when there
    is none) doesn't block the rest.
    """
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    kept: list[Step] = []
    skipped: list[str] = []
    for step in steps:
        try:
            changed, result = _RUN[step.op](out, step)
            if changed.empty:
                raise CleanError(f"'{result.description}' would remove every row.")
        except CleanError as exc:
            skipped.append(str(exc))
            continue
        out = changed
        kept.append(step)
    return kept, skipped


# ------------------------------------------------------------------ suggestions


def suggestions(df: pd.DataFrame, limit: int = 6) -> list[dict[str, Any]]:
    """Fixes the app can see for itself, most valuable first, each as ready-made steps."""
    found: list[tuple[float, str, list[Step]]] = []

    duplicates = int(df.duplicated().sum())
    if duplicates:
        label = f"Remove {_plural(duplicates, 'duplicate row')}"
        found.append((0.9, label, [Step("remove_duplicates")]))

    for col in df.columns:
        series, name = df[col], str(col)
        missing = float(series.isna().mean())
        if missing >= 0.6:
            label = f"Remove {name} ({missing * 100:.0f}% empty)"
            found.append((0.8 + missing / 10, label, [Step("drop_columns", columns=[name])]))
        elif missing > 0:
            numeric = pd.api.types.is_numeric_dtype(series)
            method = "median" if numeric and series.nunique() > 5 else "mode"
            word = "the median" if method == "median" else "the most common value"
            cells = _plural(int(series.isna().sum()), "empty cell")
            label = f"Fill {cells} in {name} with {word}"
            found.append((0.4 + missing, label, [Step("fill_missing", column=name, method=method)]))
        if _is_text(series) and 1 < series.nunique() <= 200:
            merges = _spelling_merges(series, name)
            if merges:
                first = merges[0]
                label = (
                    f"Tidy {_plural(len(merges), 'inconsistent spelling')} in {name} "
                    f"('{first.values[0]}' becomes '{first.value}')"
                )
                found.append((0.7, label, merges))
    found.sort(key=lambda item: -item[0])
    return [
        {"label": label, "steps": [s.to_dict() for s in steps]} for _, label, steps in found[:limit]
    ]


def _spelling_merges(series: pd.Series, name: str, limit: int = 8) -> list[Step]:
    """Values that differ only by letter case or spaces, merged into the commonest form."""
    text = series.dropna().astype("string")
    key = text.str.strip().str.lower()
    merges: list[tuple[int, Step]] = []
    for _, group in text.groupby(key):
        variants = group.value_counts()
        if len(variants) < 2:
            continue
        best = str(variants.index[0]).strip()
        others = [str(v) for v in variants.index[1:]]
        step = Step("replace_values", column=name, values=others, value=best)
        merges.append((int(variants.iloc[1:].sum()), step))
    merges.sort(key=lambda item: -item[0])
    return [step for _, step in merges[:limit]]


def preview_dict(preview: CleanPreview) -> dict[str, Any]:
    """JSON form of a preview."""
    return {
        "rows_before": preview.rows_before,
        "rows_after": preview.rows_after,
        "columns_before": preview.columns_before,
        "columns_after": preview.columns_after,
        "steps": [
            {
                "step": r.step.to_dict(),
                "description": r.description,
                "effect": r.effect,
                "rows_removed": r.rows_removed,
                "cells_changed": r.cells_changed,
                "columns_removed": r.columns_removed,
            }
            for r in preview.steps
        ],
    }
