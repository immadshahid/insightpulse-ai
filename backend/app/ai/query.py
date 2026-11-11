"""Ask-AI query plans: schema, validation against real data, and a pandas executor.

The LLM never writes code. It fills a small JSON plan
``{metric, group_by, filter, period, compare, sort, limit, chart}`` whose allowed values
come from the dataset's actual columns. The plan is validated here (unknown products,
months or fields are rejected with a helpful message) and executed with fixed pandas
operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pandas.api.types import is_numeric_dtype
from pydantic import BaseModel, Field

from app.insights.base import ChartSpec, compact_number, fmt_money, has, jsonable, pct_change
from app.pipeline.cleaner import WEEKDAYS

METRIC_LABELS = {
    "revenue": "Revenue",
    "orders": "Orders",
    "units": "Units sold",
    "customers": "Customers",
    "avg_order_value": "Average order value",
    "profit": "Profit",
    "cost": "Cost",
}
TIME_DIMS = ("day", "week", "month", "hour")
MONEY_METRICS = ("revenue", "avg_order_value", "profit", "cost")
_WEEKDAY_NAMES = {d.lower(): d for d in WEEKDAYS} | {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}
MAX_LIMIT = 50
MAX_TIME_POINTS = 120


class PlanError(ValueError):
    """The plan can't run on this dataset (message is shown to the user)."""


class PlanFilter(BaseModel):
    """Keep (eq) or drop (neq) rows whose ``field`` is one of ``values``."""

    field: str
    op: Literal["eq", "neq"] = "eq"
    values: list[str]


class PlanPeriod(BaseModel):
    """Date window, relative to the last date in the data."""

    type: Literal["all", "last_n_days", "month", "between"] = "all"
    n_days: int | None = None
    month: str | None = None
    start: str | None = None
    end: str | None = None


class QueryPlan(BaseModel):
    """What the LLM returns for a question."""

    answerable: bool = True
    reason: str | None = None
    metric: str = "revenue"
    group_by: str | None = None
    filter: list[PlanFilter] = Field(default_factory=list)
    period: PlanPeriod = Field(default_factory=PlanPeriod)
    compare: Literal["none", "previous_period", "same_period_last_year"] = "none"
    sort: Literal["desc", "asc", "chronological"] = "desc"
    limit: int | None = None
    chart: Literal["auto", "bar", "line", "donut", "none"] = "auto"


@dataclass(frozen=True)
class DatasetSchema:
    """Metrics and dimensions a question may use for this dataset."""

    metrics: list[str]
    dimensions: list[str]
    filterable: list[str]
    date_min: pd.Timestamp
    date_max: pd.Timestamp
    currency: str | None

    @classmethod
    def from_frame(cls, df: pd.DataFrame, currency: str | None) -> DatasetSchema:
        """Inspect the clean frame."""
        metrics = ["revenue", "orders", "avg_order_value"]
        if has(df, "quantity"):
            metrics.append("units")
        if has(df, "customer"):
            metrics.append("customers")
        metrics += [m for m in ("profit", "cost") if m in df and is_numeric_dtype(df[m])]
        cats = [c for c in ("product", "region", "customer") if has(df, c)]
        times = ["day", "week", "month", "weekday"] + (["hour"] if "hour" in df else [])
        return cls(
            metrics=metrics,
            dimensions=cats + times,
            filterable=cats + ["month", "weekday"],
            date_min=df["date"].min().normalize(),
            date_max=df["date"].max().normalize(),
            currency=currency,
        )


def plan_schema(ds: DatasetSchema) -> dict[str, Any]:
    """JSON schema whose enums are this dataset's real metrics and dimensions."""
    nullable_str = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_int = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "reason": nullable_str,
            "metric": {"type": "string", "enum": ds.metrics},
            "group_by": {"anyOf": [{"type": "string", "enum": ds.dimensions}, {"type": "null"}]},
            "filter": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": ds.filterable},
                        "op": {"type": "string", "enum": ["eq", "neq"]},
                        "values": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["field", "op", "values"],
                    "additionalProperties": False,
                },
            },
            "period": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["all", "last_n_days", "month", "between"]},
                    "n_days": nullable_int,
                    "month": nullable_str,
                    "start": nullable_str,
                    "end": nullable_str,
                },
                "required": ["type", "n_days", "month", "start", "end"],
                "additionalProperties": False,
            },
            "compare": {
                "type": "string",
                "enum": ["none", "previous_period", "same_period_last_year"],
            },
            "sort": {"type": "string", "enum": ["desc", "asc", "chronological"]},
            "limit": nullable_int,
            "chart": {"type": "string", "enum": ["auto", "bar", "line", "donut", "none"]},
        },
        "required": [
            "answerable",
            "reason",
            "metric",
            "group_by",
            "filter",
            "period",
            "compare",
            "sort",
            "limit",
            "chart",
        ],
        "additionalProperties": False,
    }


# ------------------------------------------------------------------ validation
def _resolve_values(df: pd.DataFrame, field: str, values: list[str]) -> list[str]:
    """Map user/LLM wording to exact stored values (case-insensitive, unique substring)."""
    if field == "weekday":
        out = []
        for v in values:
            key = v.strip().lower()
            if key not in _WEEKDAY_NAMES:
                raise PlanError(f"'{v}' is not a weekday.")
            out.append(_WEEKDAY_NAMES[key])
        return out
    known = sorted(df[field].dropna().astype(str).unique())
    lower = {k.lower(): k for k in known}
    out = []
    for v in values:
        key = v.strip().lower()
        if key in lower:
            out.append(lower[key])
            continue
        partial = [k for k in known if key and key in k.lower()]
        if len(partial) == 1:
            out.append(partial[0])
            continue
        label = field.replace("_", " ")
        hint = ", ".join(known[:8]) if field != "customer" else ""
        raise PlanError(
            f"I couldn't find '{v}' in your {label} values."
            + (f" Known values include: {hint}." if hint else "")
        )
    return out


def validate_plan(plan: QueryPlan, df: pd.DataFrame, ds: DatasetSchema) -> QueryPlan:
    """Check every field against the dataset; returns a cleaned copy of the plan."""
    if plan.metric not in ds.metrics:
        raise PlanError(f"This dataset can't measure '{plan.metric}'.")
    if plan.group_by is not None and plan.group_by not in ds.dimensions:
        raise PlanError(f"This dataset can't be broken down by '{plan.group_by}'.")
    filters = []
    for f in plan.filter:
        if f.field not in ds.filterable:
            raise PlanError(f"This dataset can't be filtered by '{f.field}'.")
        if f.field == "month":
            months = set(df["month"].unique())
            bad = [v for v in f.values if v not in months]
            if bad:
                raise PlanError(f"No data for month(s): {', '.join(bad)}.")
            filters.append(f)
        else:
            filters.append(f.model_copy(update={"values": _resolve_values(df, f.field, f.values)}))
    period = plan.period
    if period.type == "last_n_days":
        n = period.n_days or 30
        period = period.model_copy(update={"n_days": max(1, min(int(n), 3650))})
    elif period.type == "month":
        if not period.month or period.month not in set(df["month"].unique()):
            raise PlanError(f"No data for {period.month or 'that month'}.")
    elif period.type == "between":
        try:
            start, end = pd.Timestamp(period.start), pd.Timestamp(period.end)
        except (TypeError, ValueError) as exc:
            raise PlanError("I couldn't understand that date range.") from exc
        if start > end:
            start, end = end, start
        period = period.model_copy(
            update={"start": start.date().isoformat(), "end": end.date().isoformat()}
        )
    limit = plan.limit
    if limit is not None:
        limit = max(1, min(int(limit), MAX_LIMIT))
    return plan.model_copy(update={"filter": filters, "period": period, "limit": limit})


# ------------------------------------------------------------------ execution
class ResultRow(BaseModel):
    """One group of the answer."""

    label: str
    value: float
    previous: float | None = None
    change_pct: float | None = None
    share: float | None = None


class QueryResult(BaseModel):
    """Computed numbers the answer is written from."""

    metric: str
    metric_label: str
    group_by: str | None
    start: str
    end: str
    period_label: str
    compare_label: str | None
    total: float
    previous_total: float | None
    change_pct: float | None
    rows: list[ResultRow]
    groups_total: int
    source_rows: int
    currency: str | None


def window(plan: QueryPlan, ds: DatasetSchema) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive [start, end] dates for the plan's period."""
    p = plan.period
    if p.type == "last_n_days":
        return ds.date_max - pd.Timedelta(days=p.n_days - 1), ds.date_max
    if p.type == "month":
        start = pd.Timestamp(p.month + "-01")
        return start, start + pd.offsets.MonthEnd(0)
    if p.type == "between":
        return pd.Timestamp(p.start), pd.Timestamp(p.end)
    return ds.date_min, ds.date_max


def _slice(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    day = df["date"].dt.normalize()
    return df[(day >= start) & (day <= end)]


def _apply_filters(df: pd.DataFrame, plan: QueryPlan) -> pd.DataFrame:
    for f in plan.filter:
        mask = df[f.field].astype(str).isin(f.values)
        df = df[mask] if f.op == "eq" else df[~mask]
    return df


def _metric(d: pd.DataFrame, metric: str, by: pd.Series | None = None) -> pd.Series | float:
    """Metric for a frame, or per group when ``by`` is given."""
    g = d.groupby(by, observed=True) if by is not None else None
    order_key = "order_id" if has(d, "order_id") else None

    def orders(x: Any) -> Any:
        if order_key:
            return x[order_key].nunique()
        return x["revenue"].size() if g is not None else float(len(d))

    if metric in ("revenue", "profit", "cost"):
        return (g if g is not None else d)[metric].sum()
    if metric == "units":
        return (g if g is not None else d)["quantity"].sum()
    if metric == "customers":
        return (g if g is not None else d)["customer"].nunique()
    if metric == "orders":
        return orders(g if g is not None else d)
    rev = (g if g is not None else d)["revenue"].sum()
    cnt = orders(g if g is not None else d)
    return rev / cnt.replace(0, pd.NA) if g is not None else (rev / cnt if cnt else 0.0)


def _group_key(d: pd.DataFrame, dim: str) -> pd.Series:
    if dim == "day":
        return d["date"].dt.strftime("%Y-%m-%d")
    if dim == "week":
        return (
            d["date"].dt.normalize() - pd.to_timedelta(d["date"].dt.weekday, unit="D")
        ).dt.strftime("%Y-%m-%d")
    if dim == "hour":
        return d["hour"].astype(int).map(lambda h: f"{h:02d}:00")
    return d[dim].astype(str)


def _human_date(ts: pd.Timestamp) -> str:
    return f"{ts.day} {ts:%b %Y}"


def run_plan(df: pd.DataFrame, plan: QueryPlan, ds: DatasetSchema) -> QueryResult:
    """Execute a validated plan with fixed pandas operations."""
    start, end = window(plan, ds)
    base = _apply_filters(df, plan)
    cur = _slice(base, start, end)

    prev = None
    compare_label = None
    if plan.compare != "none" and plan.period.type != "all":
        if plan.compare == "previous_period":
            length = end - start + pd.Timedelta(days=1)
            p_start, p_end = start - length, start - pd.Timedelta(days=1)
        else:
            p_start, p_end = start - pd.DateOffset(years=1), end - pd.DateOffset(years=1)
        prev = _slice(base, p_start, p_end)
        compare_label = f"{_human_date(p_start)} - {_human_date(p_end)}"
        if prev.empty:
            prev, compare_label = None, None

    total = float(_metric(cur, plan.metric)) if len(cur) else 0.0
    prev_total = float(_metric(prev, plan.metric)) if prev is not None else None

    rows: list[ResultRow] = []
    groups_total = 0
    if plan.group_by and len(cur):
        values = _metric(cur, plan.metric, _group_key(cur, plan.group_by)).astype(float)
        groups_total = len(values)
        prev_values = (
            _metric(prev, plan.metric, _group_key(prev, plan.group_by))
            if prev is not None and plan.group_by not in TIME_DIMS
            else None
        )
        time_like = plan.group_by in TIME_DIMS or plan.group_by == "weekday"
        if plan.group_by == "weekday":
            values = values.reindex([d for d in WEEKDAYS if d in values.index])
        if plan.sort == "chronological" or (
            time_like and plan.sort != "asc" and plan.limit is None
        ):
            values = values if plan.group_by == "weekday" else values.sort_index()
        else:
            values = values.sort_values(ascending=plan.sort == "asc")
        limit = plan.limit or (MAX_TIME_POINTS if time_like else 10)
        values = values.iloc[-limit:] if time_like and plan.limit is None else values.iloc[:limit]
        additive = plan.metric in ("revenue", "units", "orders")
        for label, v in values.items():
            pv = (
                float(prev_values.get(label))
                if prev_values is not None and label in prev_values.index
                else None
            )
            rows.append(
                ResultRow(
                    label=str(label),
                    value=round(float(v), 2),
                    previous=round(pv, 2) if pv is not None else None,
                    change_pct=pct_change(float(v), pv) if pv is not None else None,
                    share=round(float(v) / total, 4) if additive and total else None,
                )
            )

    period_label = (
        f"{_human_date(start)} - {_human_date(end)}"
        if plan.period.type != "all"
        else f"all data ({_human_date(start)} - {_human_date(end)})"
    )
    return QueryResult(
        metric=plan.metric,
        metric_label=METRIC_LABELS[plan.metric],
        group_by=plan.group_by,
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        period_label=period_label,
        compare_label=compare_label,
        total=round(total, 2),
        previous_total=round(prev_total, 2) if prev_total is not None else None,
        change_pct=pct_change(total, prev_total) if prev_total is not None else None,
        rows=rows,
        groups_total=groups_total,
        source_rows=int(len(cur)),
        currency=ds.currency,
    )


# ------------------------------------------------------------------ presentation
def describe(plan: QueryPlan, result: QueryResult) -> str:
    """Deterministic 'how I got this' line."""
    verb = {
        "revenue": "Summed revenue",
        "units": "Summed units sold",
        "orders": "Counted orders",
        "customers": "Counted distinct customers",
        "avg_order_value": "Divided revenue by orders",
        "profit": "Summed profit",
        "cost": "Summed cost",
    }[plan.metric]
    parts = [verb]
    if plan.group_by:
        parts.append(f"by {plan.group_by}")
    parts.append(f"for {result.period_label}")
    for f in plan.filter:
        word = "only" if f.op == "eq" else "excluding"
        parts.append(f"{word} {f.field} = {', '.join(f.values)}")
    text = " ".join(parts)
    if plan.group_by and result.groups_total > len(result.rows):
        text += f", showing {len(result.rows)} of {result.groups_total}"
    if result.compare_label:
        text += f", compared with {result.compare_label}"
    return text + f". Based on {result.source_rows:,} order lines."


def fmt_metric(value: float, metric: str, currency: str | None) -> str:
    """Format a metric value for text."""
    if metric in MONEY_METRICS:
        return fmt_money(value, currency)
    return compact_number(value) if value >= 10_000 else f"{value:,.0f}"


def template_answer(result: QueryResult) -> str:
    """Plain answer built from the numbers, used when the LLM can't write one."""
    m, c = result.metric, result.currency
    if result.source_rows == 0:
        return "There is no data for that selection."
    text = f"{result.metric_label} for {result.period_label}: {fmt_metric(result.total, m, c)}"
    if result.change_pct is not None:
        direction = "up" if result.change_pct >= 0 else "down"
        text += f", {direction} {abs(result.change_pct):.1f}% on {result.compare_label}"
    text += "."
    if result.rows:
        time_like = result.group_by in (*TIME_DIMS, "weekday")
        ranked_asc = not time_like and result.rows[0].value <= result.rows[-1].value
        if time_like:
            top = max(result.rows, key=lambda r: r.value)
            text += f" The highest was {top.label} with {fmt_metric(top.value, m, c)}"
        else:
            top = result.rows[0]
            word = "lowest" if ranked_asc and len(result.rows) > 1 else "top"
            text += f" {top.label} is {word} with {fmt_metric(top.value, m, c)}"
        text += f" ({top.share * 100:.0f}% of the total)." if top.share else "."
    return text


def chart_for(plan: QueryPlan, result: QueryResult) -> ChartSpec | None:
    """Chart matching the question: line over time, bars for rankings, donut for shares."""
    if not result.rows or plan.chart == "none":
        return None
    labels = [r.label for r in result.rows]
    values = [r.value for r in result.rows]
    fmt = "money" if plan.metric in MONEY_METRICS else "number"
    time_dim = plan.group_by in ("day", "week", "month")
    kind = plan.chart
    if kind == "auto":
        kind = "line" if time_dim or plan.group_by == "hour" else "bar"
    if kind == "donut" and len(labels) <= 6 and all(v >= 0 for v in values):
        return ChartSpec(
            kind="donut",
            payload=jsonable(
                {
                    "labels": labels,
                    "values": values,
                    "center_value": fmt_metric(result.total, plan.metric, result.currency),
                    "center_label": result.metric_label,
                }
            ),
        )
    if kind == "line" and len(labels) >= 2:
        x = [f"{lbl}-01" if plan.group_by == "month" else lbl for lbl in labels]
        return ChartSpec(
            kind="line",
            payload=jsonable(
                {
                    "x": x if time_dim else list(range(len(labels))),
                    "x_is_date": time_dim,
                    "series": [{"name": result.metric_label, "y": values, "role": "actual"}],
                    "y_format": fmt,
                    "markers": "points" if len(labels) <= 14 else None,
                }
            ),
        )
    keep_order = plan.group_by in ("weekday", "hour") or time_dim
    return ChartSpec(
        kind="bar_ranking",
        payload=jsonable(
            {
                "labels": labels[:12],
                "values": values[:12],
                "highlight": [values[:12].index(max(values[:12]))],
                "value_format": fmt,
                "horizontal": not keep_order,
                "keep_order": keep_order,
            }
        ),
    )
