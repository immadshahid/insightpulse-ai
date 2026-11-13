"""Exploratory data analysis for any table: overview, columns, charts and findings.

Works on whatever the user uploads (Titanic, a survey, HR records...). Kinds come from the
profiler; a numeric column with two values (0/1) is treated as a yes/no category.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.insights.base import ChartSpec, Insight, compact_number, jsonable

MAX_DIST_CHARTS = 4
MAX_CATEGORY_CHARTS = 4
TOP_VALUES = 8
TARGET_HINTS = re.compile(
    r"(surviv|target|label|outcome|churn|class|default|fraud|result|status|y$|attrition|"
    r"left|converted|purchased|diagnosis|approved|passed)",
    re.IGNORECASE,
)


@dataclass
class ColumnSummary:
    """What one column holds."""

    name: str
    kind: str  # numeric | category | yes/no | date | text | id
    missing_pct: float
    unique: int
    stats: list[tuple[str, str]]  # label, value
    top_values: list[tuple[str, int, float]] = field(default_factory=list)  # value, count, share


@dataclass
class ExploreChart:
    """A chart with a title and a one-line takeaway."""

    title: str
    caption: str
    spec: ChartSpec


@dataclass
class Exploration:
    """Everything the Explore screen and the data report show."""

    overview: dict[str, Any]
    columns: list[ColumnSummary]
    charts: list[ExploreChart]
    insights: list[Insight]
    target: str | None
    predictable: list[str]
    quality: dict[str, Any]
    outcome_copies: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers


def _fmt(v: float) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    a = abs(v)
    if a >= 10_000:
        return compact_number(v)
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def column_kinds(df: pd.DataFrame, profile_kinds: dict[str, str]) -> dict[str, str]:
    """Analysis kind for each column."""
    out: dict[str, str] = {}
    for col in df.columns:
        s = df[col]
        base = profile_kinds.get(col)
        nunique = s.nunique(dropna=True)
        if pd.api.types.is_datetime64_any_dtype(s) or base == "datetime":
            out[col] = "date"
        elif pd.api.types.is_numeric_dtype(s):
            if nunique == 2:
                out[col] = "yes/no"
            elif base == "identifier" or _looks_like_id(col, s):
                out[col] = "id"
            elif nunique <= 10 and pd.api.types.is_integer_dtype(s.dropna()):
                out[col] = "category"  # e.g. passenger class 1/2/3, ratings 1-5
            else:
                out[col] = "numeric"
        elif nunique == 2:
            out[col] = "yes/no"
        elif base == "identifier" or (len(s) > 30 and nunique / max(1, s.notna().sum()) > 0.9):
            out[col] = "id"
        elif base == "text" and nunique > 50:
            out[col] = "text"
        else:
            out[col] = "category"
    return out


def _looks_like_id(name: str, s: pd.Series) -> bool:
    lowered = name.lower()
    words = set(re.split(r"[^a-z0-9]+", lowered))
    named_like_id = "id" in words or lowered.endswith("id") or "number" in words
    return named_like_id and s.nunique() > 0.9 * max(1, s.notna().sum())


def _rate_label(value: Any) -> str:
    return (
        str(int(value))
        if isinstance(value, (float, np.floating)) and float(value).is_integer()
        else str(value)
    )


def _positive_value(s: pd.Series) -> Any:
    """Which of two values means 'yes' (1, True, yes, survived...), for rates."""
    values = list(s.dropna().unique())
    for v in values:
        if str(v).strip().lower() in (
            "1",
            "1.0",
            "true",
            "yes",
            "y",
            "survived",
            "positive",
            "churned",
        ):
            return v
    return sorted(values, key=str)[-1]


def suggest_target(df: pd.DataFrame, kinds: dict[str, str]) -> str | None:
    """A column that looks like an outcome to explain (Survived, Churn, Outcome...)."""
    candidates = [c for c, k in kinds.items() if k in ("yes/no", "category")]
    named = [c for c in candidates if TARGET_HINTS.search(c)]
    yes_no_named = [c for c in named if kinds[c] == "yes/no"]
    if yes_no_named:
        return yes_no_named[0]
    if named:
        return named[0]
    return None


def outcome_copies(df: pd.DataFrame, target: str, kinds: dict[str, str]) -> list[str]:
    """Columns that restate the outcome (e.g. 'alive' yes/no next to 'survived' 1/0).

    They would trivially "explain" it, so findings and models leave them out.
    """
    copies = []
    t = df[target]
    numeric_target = kinds.get(target) == "numeric"
    for col, kind in kinds.items():
        if col == target or kind in ("id", "text"):
            continue
        d = df[[col, target]].dropna()
        if len(d) < 20:
            continue
        if numeric_target:
            if kind == "numeric" and abs(d[col].corr(d[target])) >= 0.999:
                copies.append(col)
            continue
        if d[col].nunique() > 2 * max(2, t.nunique()):
            continue
        a, b = d[col].astype(str), d[target].astype(str)
        pure = pd.crosstab(a, b).max(axis=1).sum() / len(d)
        back = pd.crosstab(b, a).max(axis=1).sum() / len(d)
        if pure >= 0.995 and back >= 0.995:
            copies.append(col)
    return copies


def predictable_columns(kinds: dict[str, str]) -> list[str]:
    """Columns a model can predict: yes/no, categories and numbers (not ids, text or dates)."""
    return [c for c, k in kinds.items() if k in ("yes/no", "category", "numeric")]


# ------------------------------------------------------------------ main


def explore(
    df: pd.DataFrame,
    profile_kinds: dict[str, str] | None = None,
    cleaning: dict[str, Any] | None = None,
    target: str | None = None,
) -> Exploration:
    """Full EDA of ``df``. ``target`` (optional) is the outcome column to explain."""
    kinds = column_kinds(df, profile_kinds or {})
    target = target if target in kinds else suggest_target(df, kinds)
    n_rows, n_cols = len(df), len(df.columns)
    missing_cells = int(df.isna().sum().sum())
    total_cells = max(1, n_rows * n_cols)
    counts: dict[str, int] = {}
    for k in kinds.values():
        counts[k] = counts.get(k, 0) + 1
    cleaning = cleaning or {}
    overview = {
        "rows": n_rows,
        "columns": n_cols,
        "numeric_columns": counts.get("numeric", 0),
        "category_columns": counts.get("category", 0) + counts.get("yes/no", 0),
        "date_columns": counts.get("date", 0),
        "text_columns": counts.get("text", 0) + counts.get("id", 0),
        "missing_cells_pct": round(missing_cells / total_cells * 100, 2),
        "complete_rows_pct": round(float(df.notna().all(axis=1).mean() * 100) if n_rows else 0, 1),
        "duplicate_rows": int(cleaning.get("duplicate_rows", 0)),
    }

    copies = outcome_copies(df, target, kinds) if target else []
    columns = [_summarise(df[c], c, kinds[c]) for c in df.columns]
    charts = _charts(df, kinds, target, set(copies))
    insights = _insights(df, kinds, target, overview, copies)
    quality = _quality(overview, columns)
    return Exploration(
        overview=overview,
        columns=columns,
        charts=charts,
        insights=insights,
        target=target,
        predictable=predictable_columns(kinds),
        quality=quality,
        outcome_copies=copies,
    )


def _summarise(s: pd.Series, name: str, kind: str) -> ColumnSummary:
    present = s.dropna()
    missing = float(s.isna().mean() * 100) if len(s) else 0.0
    stats: list[tuple[str, str]] = []
    top: list[tuple[str, int, float]] = []
    if kind == "numeric" and len(present):
        q1, q3 = present.quantile(0.25), present.quantile(0.75)
        iqr = q3 - q1
        outliers = (
            int(((present < q1 - 1.5 * iqr) | (present > q3 + 1.5 * iqr)).sum()) if iqr else 0
        )
        stats = [
            ("Average", _fmt(float(present.mean()))),
            ("Median", _fmt(float(present.median()))),
            ("Std. dev.", _fmt(float(present.std() or 0))),
            ("Min", _fmt(float(present.min()))),
            ("Max", _fmt(float(present.max()))),
            ("Outliers", f"{outliers:,}"),
        ]
    elif kind == "date" and len(present):
        stats = [
            ("From", f"{present.min():%d %b %Y}"),
            ("To", f"{present.max():%d %b %Y}"),
        ]
    if kind in ("category", "yes/no", "text", "id") and len(present):
        vc = present.astype(str).value_counts()
        top = [
            (str(k), int(v), round(float(v) / len(present) * 100, 1)) for k, v in vc.head(5).items()
        ]
        if kind == "id":
            stats = [("Distinct", f"{present.nunique():,}")]
    return ColumnSummary(name, kind, round(missing, 1), int(present.nunique()), stats, top)


def _charts(
    df: pd.DataFrame, kinds: dict[str, str], target: str | None, skip: set[str] | None = None
) -> list[ExploreChart]:
    charts: list[ExploreChart] = []
    missing = (df.isna().mean() * 100).round(1)
    missing = missing[missing > 0].sort_values(ascending=False).head(10)
    if len(missing):
        charts.append(
            ExploreChart(
                "Missing values",
                f"{missing.index[0]} is missing in {missing.iloc[0]:.0f}% of rows.",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            "labels": [str(c) for c in missing.index],
                            "values": missing.tolist(),
                            "highlight": [0],
                            "value_format": "percent",
                        }
                    ),
                ),
            )
        )

    if target:
        kept = {c: k for c, k in kinds.items() if c not in (skip or set())}
        charts += _target_charts(df, kept, target)

    numeric = [c for c, k in kinds.items() if k == "numeric"]
    if len(numeric) >= 2:
        corr = df[numeric].corr()
        if corr.notna().sum().sum() > len(numeric):
            pairs = [
                (a, b, float(corr.loc[a, b]))
                for i, a in enumerate(numeric)
                for b in numeric[i + 1 :]
                if pd.notna(corr.loc[a, b])
            ]
            a, b, r = max(pairs, key=lambda x: abs(x[2]))
            charts.append(
                ExploreChart(
                    "How the numbers relate",
                    f"Strongest link: {a} and {b} (r = {r:.2f}).",
                    ChartSpec(
                        kind="corr_heatmap",
                        payload=jsonable(
                            {
                                "labels": numeric[:8],
                                "matrix": corr.loc[numeric[:8], numeric[:8]]
                                .round(2)
                                .values.tolist(),
                            }
                        ),
                    ),
                )
            )

    for col in numeric[:MAX_DIST_CHARTS]:
        s = df[col].dropna()
        if len(s) < 5:
            continue
        clip = s[s <= s.quantile(0.99)] if len(s) > 100 else s
        charts.append(
            ExploreChart(
                f"Distribution of {col}",
                f"Median {_fmt(float(s.median()))}, average {_fmt(float(s.mean()))}, "
                f"from {_fmt(float(s.min()))} to {_fmt(float(s.max()))}.",
                ChartSpec(
                    kind="distribution", payload=jsonable({"values": clip.tolist(), "label": col})
                ),
            )
        )

    cats = [c for c, k in kinds.items() if k in ("category", "yes/no") and c != target]
    for col in cats[:MAX_CATEGORY_CHARTS]:
        vc = df[col].dropna().astype(str).value_counts().head(TOP_VALUES)
        if len(vc) < 2:
            continue
        share = vc.iloc[0] / df[col].notna().sum() * 100
        charts.append(
            ExploreChart(
                f"{col}: most common values",
                f"{vc.index[0]} is the most common ({share:.0f}% of rows).",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            "labels": [str(i) for i in vc.index],
                            "values": vc.tolist(),
                            "highlight": [0],
                        }
                    ),
                ),
            )
        )
    return charts


def _group_rates(df: pd.DataFrame, target: str, col: str, positive: Any) -> pd.Series:
    d = df[[col, target]].dropna()
    if len(d) < 10:
        return pd.Series(dtype=float)
    groups = d.groupby(d[col].astype(str))[target]
    sizes = groups.size()
    rates = groups.apply(lambda s: (s == positive).mean() * 100)
    return rates[sizes >= max(5, len(d) * 0.02)].sort_values(ascending=False).head(TOP_VALUES)


def _target_charts(df: pd.DataFrame, kinds: dict[str, str], target: str) -> list[ExploreChart]:
    out: list[ExploreChart] = []
    t = df[target]
    if kinds.get(target) != "yes/no":
        vc = t.dropna().astype(str).value_counts().head(TOP_VALUES)
        out.append(
            ExploreChart(
                f"{target}: how the outcomes split",
                f"{vc.index[0]} is the most common outcome.",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {"labels": list(vc.index), "values": vc.tolist(), "highlight": [0]}
                    ),
                ),
            )
        )
        return out
    positive = _positive_value(t)
    overall = float((t.dropna() == positive).mean() * 100)
    label = f"{target} = {_rate_label(positive)}"
    best: list[tuple[float, str, pd.Series]] = []
    for col, kind in kinds.items():
        if col == target or kind not in ("category", "yes/no"):
            continue
        rates = _group_rates(df, target, col, positive)
        if len(rates) >= 2:
            best.append((float(rates.max() - rates.min()), col, rates))
    for _gap, col, rates in sorted(best, key=lambda x: -x[0])[:3]:
        out.append(
            ExploreChart(
                f"{label} by {col}",
                f"{rates.index[0]}: {rates.iloc[0]:.0f}% vs "
                f"{rates.index[-1]}: {rates.iloc[-1]:.0f}% "
                f"(overall {overall:.0f}%).",
                ChartSpec(
                    kind="bar_ranking",
                    payload=jsonable(
                        {
                            "labels": [str(i) for i in rates.index],
                            "values": rates.round(1).tolist(),
                            "highlight": [0],
                            "value_format": "percent",
                        }
                    ),
                ),
            )
        )
    return out


def _insight(
    iid: str, category: str, tag: str, headline: str, why: str, score: float, **data
) -> Insight:
    return Insight(
        id=iid,
        kind=iid.split(":")[0],
        category=category,
        tag=tag,
        headline=headline,
        why_it_matters=why,
        score=max(0.0, min(1.0, score)),
        data=jsonable(data),
    )


def _insights(
    df: pd.DataFrame,
    kinds: dict[str, str],
    target: str | None,
    overview: dict,
    copies: list[str] | None = None,
) -> list[Insight]:
    found: list[Insight] = []
    for col in copies or []:
        found.append(
            _insight(
                f"outcome_copy:{col}",
                "quality",
                "Left out",
                f"{col} repeats {target}, so it is left out of the findings",
                f"Every value of {col} lines up with one value of {target}, so it is the "
                "same information under another name. Predict leaves it out too.",
                0.9,
                column=col,
                target=target,
            )
        )
    gap_kinds = {c: k for c, k in kinds.items() if c not in (copies or [])}
    n = max(1, len(df))

    if target and kinds.get(target) == "yes/no":
        positive = _positive_value(df[target])
        overall = float((df[target].dropna() == positive).mean() * 100)
        found.append(
            _insight(
                "target_rate",
                "target",
                "Outcome",
                f"{overall:.0f}% of rows have {target} = {_rate_label(positive)}",
                "This is the baseline: any group above or below it is worth a closer look. "
                "Use Predict to see what drives it.",
                0.95,
                target=target,
                rate=overall,
            )
        )
        gaps = []
        for col, kind in gap_kinds.items():
            if col != target and kind in ("category", "yes/no"):
                rates = _group_rates(df, target, col, positive)
                if len(rates) >= 2:
                    gaps.append((float(rates.max() - rates.min()), col, rates))
        for gap, col, rates in sorted(gaps, key=lambda x: -x[0])[:3]:
            found.append(
                _insight(
                    f"target_gap:{col}",
                    "target",
                    "What makes a difference",
                    f"{target} rate is {rates.iloc[0]:.0f}% for {col} = {rates.index[0]} "
                    f"vs {rates.iloc[-1]:.0f}% for {rates.index[-1]}",
                    f"A {gap:.0f}-point gap: {col} is strongly linked to {target}. "
                    "Linked does not always mean it causes it.",
                    0.6 + min(0.35, gap / 200),
                    column=col,
                    gap=gap,
                )
            )

    missing = df.isna().mean() * 100
    for col, pct in missing[missing >= 5].sort_values(ascending=False).head(3).items():
        found.append(
            _insight(
                f"missing:{col}",
                "quality",
                "Data quality",
                f"{col} is missing in {pct:.0f}% of rows",
                "Results that use this column only cover the rows where it is filled in. "
                + (
                    "Consider dropping it."
                    if pct > 60
                    else "Filling the gaps would make analysis more reliable."
                ),
                0.4 + min(0.4, pct / 150),
                column=col,
                missing_pct=round(float(pct), 1),
            )
        )

    numeric = [c for c, k in kinds.items() if k == "numeric"]
    if len(numeric) >= 2:
        corr = df[numeric].corr()
        pairs = sorted(
            (
                (a, b, float(corr.loc[a, b]))
                for i, a in enumerate(numeric)
                for b in numeric[i + 1 :]
                if pd.notna(corr.loc[a, b]) and abs(corr.loc[a, b]) >= 0.4
            ),
            key=lambda x: -abs(x[2]),
        )
        for a, b, r in pairs[:2]:
            direction = "rises" if r > 0 else "falls"
            found.append(
                _insight(
                    f"correlation:{a}:{b}",
                    "relationships",
                    "Relationship",
                    f"When {a} goes up, {b} {direction} (r = {r:.2f})",
                    "A strong link between two columns. It may be cause and effect, or both may "
                    "depend on something else.",
                    0.5 + abs(r) * 0.4,
                    a=a,
                    b=b,
                    r=r,
                )
            )

    for col in numeric:
        s = df[col].dropna()
        if len(s) < 20:
            continue
        skew = float(s.skew())
        if abs(skew) >= 1.5:
            found.append(
                _insight(
                    f"skew:{col}",
                    "distributions",
                    "Distribution",
                    f"{col} is lopsided: median {_fmt(float(s.median()))} vs average "
                    f"{_fmt(float(s.mean()))}",
                    "A few very large (or small) values pull the average away from the typical "
                    "value; the median describes a typical row better.",
                    0.35 + min(0.3, abs(skew) / 20),
                    column=col,
                    skew=skew,
                )
            )

    for col, kind in kinds.items():
        if kind not in ("category", "yes/no") or col == target:
            continue
        vc = df[col].dropna().astype(str).value_counts(normalize=True)
        if len(vc) >= 2 and vc.iloc[0] >= 0.75:
            found.append(
                _insight(
                    f"dominant:{col}",
                    "distributions",
                    "Imbalance",
                    f"{col} is mostly {vc.index[0]} ({vc.iloc[0] * 100:.0f}% of rows)",
                    "Smaller groups have few rows, so comparisons involving them are less certain.",
                    0.3,
                    column=col,
                )
            )

    if overview.get("duplicate_rows"):
        found.append(
            _insight(
                "duplicates",
                "quality",
                "Data quality",
                f"{overview['duplicate_rows']:,} rows are exact copies of another row",
                "They are kept, because different records can share the same values. If they "
                "are repeats, remove them in your file and upload it again.",
                0.3,
                count=overview["duplicate_rows"],
            )
        )

    found.sort(key=lambda i: -i.score)
    return found[:10] if n else []


def _quality(overview: dict, columns: list[ColumnSummary]) -> dict[str, Any]:
    score = 100.0 - overview["missing_cells_pct"] * 1.2
    issues = []
    for c in columns:
        if c.missing_pct >= 20:
            issues.append(
                {
                    "severity": "warning",
                    "message": f"{c.name} is missing in {c.missing_pct:.0f}% of rows.",
                }
            )
            score -= 3
    if overview["duplicate_rows"]:
        issues.append(
            {
                "severity": "info",
                "message": f"{overview['duplicate_rows']:,} rows are exact copies of another row.",
            }
        )
        score -= 2
    score = int(max(0, min(100, round(score))))
    label = (
        "Excellent" if score >= 90 else "Good" if score >= 75 else "Fair" if score >= 55 else "Poor"
    )
    return {"score": score, "label": label, "issues": issues}
