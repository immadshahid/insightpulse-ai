"""Ask AI without an LLM: reads common questions with rules and runs the same query plans.

Used when no AI key is set, or when the AI service fails. It understands metrics,
breakdowns, periods, comparisons, rankings and product or city names, and says so
plainly when a question is beyond it. Numbers come from the same pandas executor as
the LLM route, and nothing leaves the server.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import pandas as pd

from app.ai.chat import ChatAnswer, suggestions
from app.ai.query import (
    DatasetSchema,
    PlanError,
    PlanFilter,
    PlanPeriod,
    QueryPlan,
    chart_for,
    describe,
    run_plan,
    template_answer,
    validate_plan,
)
from app.insights.base import Insight, has

_INSIGHT_PREFIX = "tell me more about this:"

_MISSING = re.compile(
    r"\b(profit|margins?|costs?|expenses?|ad spend|advertis\w+|marketing|stock|inventory)\b"
)
_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_WEEKDAYS = {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}
_TIME_DIMS = ("day", "week", "month", "hour")
_NOT_UNDERSTOOD = (
    "I couldn't work out what to calculate from that. Try asking about revenue, orders, "
    "customers or products, for a period such as the last 30 days."
)


def _metric(q: str, ds: DatasetSchema) -> str | None:
    rules = [
        (r"\b(profits?|margins?)\b", "profit"),
        (r"\b(costs?|expenses?)\b", "cost"),
        (r"average order|avg order|aov|basket", "avg_order_value"),
        (r"\b(units?|quantity|pieces)\b", "units"),
        (r"how many (customers|buyers)|number of (customers|buyers)", "customers"),
        (r"\borders?\b|busiest", "orders"),
        (r"revenue|sales|sold|sell|earn|income|money|turnover", "revenue"),
    ]
    for pattern, metric in rules:
        if re.search(pattern, q) and metric in ds.metrics:
            return metric
    return None


def _group(q: str, ds: DatasetSchema) -> str | None:
    rules = [
        (r"weekday|day of (the )?week|busiest day|which day|what day", "weekday"),
        (r"\bhours?\b|time of day", "hour"),
        (r"by month|monthly|each month|per month|month by month", "month"),
        (r"by week|weekly|each week|per week", "week"),
        (r"daily|by day|each day|per day|\btrend\b", "day"),
        (r"\b(products?|items?|skus?)\b", "product"),
        (r"\b(city|cities|regions?|areas?|branch(es)?|locations?)\b", "region"),
        (r"(which|top|best|biggest|worst) (\d+ )?(customers?|buyers?)", "customer"),
    ]
    for pattern, dim in rules:
        if re.search(pattern, q) and dim in ds.dimensions:
            return dim
    return None


def _month_key(df: pd.DataFrame, name: str) -> str | None:
    wanted = f"-{_MONTHS.index(name) + 1:02d}"
    matches = sorted(m for m in df["month"].unique() if str(m).endswith(wanted))
    return matches[-1] if matches else None


def _period(q: str, df: pd.DataFrame, ds: DatasetSchema) -> PlanPeriod | None:
    last = ds.date_max
    found = re.search(r"(?:last|past|previous) (\d+) (day|week|month)s?", q)
    if found:
        days = int(found.group(1)) * {"day": 1, "week": 7, "month": 30}[found.group(2)]
        return PlanPeriod(type="last_n_days", n_days=days)
    if re.search(r"(last|previous) month", q):
        # The latest complete month: data ending on the 31st already includes it.
        current = last.to_period("M")
        month = (current if last.is_month_end else current - 1).strftime("%Y-%m")
        return PlanPeriod(type="month", month=month)
    if "this month" in q:
        return PlanPeriod(type="month", month=last.strftime("%Y-%m"))
    if re.search(r"(last|previous|past) week", q) or "this week" in q:
        return PlanPeriod(type="last_n_days", n_days=7)
    if "this year" in q:
        return PlanPeriod(type="between", start=f"{last.year}-01-01", end=str(last.date()))
    if re.search(r"(last|previous) year", q):
        year = last.year - 1
        return PlanPeriod(type="between", start=f"{year}-01-01", end=f"{year}-12-31")
    if "yesterday" in q or "today" in q:
        return PlanPeriod(type="last_n_days", n_days=1)
    dated = re.search(rf"\b({'|'.join(_MONTHS)}),? (20\d\d)\b", q)
    if dated:
        month = _MONTHS.index(dated.group(1)) + 1
        return PlanPeriod(type="month", month=f"{dated.group(2)}-{month:02d}")
    year = re.search(r"\b(?:in|for|during|of) (20\d\d)\b", q)
    if year:
        return PlanPeriod(type="between", start=f"{year[1]}-01-01", end=f"{year[1]}-12-31")
    for name in _MONTHS:
        if re.search(rf"\b(in|for|during|of) {name}\b", q):
            key = _month_key(df, name)
            if key:
                return PlanPeriod(type="month", month=key)
    return None


def _filters(q: str, df: pd.DataFrame, group: str | None) -> list[PlanFilter]:
    out = []
    for col in ("product", "region"):
        if not has(df, col) or col == group:
            continue
        hits = [
            str(v) for v in df[col].dropna().unique() if len(str(v)) >= 3 and str(v).lower() in q
        ]
        if hits:
            out.append(PlanFilter(field=col, values=[max(hits, key=len)]))
    if group != "weekday":
        days = [short for name, short in _WEEKDAYS.items() if re.search(rf"\b{name}s?\b", q)]
        if days:
            out.append(PlanFilter(field="weekday", values=days))
    return out


def build_plan(question: str, df: pd.DataFrame, ds: DatasetSchema) -> QueryPlan | None:
    """A query plan for the question, or None if nothing in it could be recognised."""
    q = question.lower()
    metric, group = _metric(q, ds), _group(q, ds)
    period, filters = _period(q, df, ds), _filters(q, df, group)
    if metric is None and group is None and period is None and not filters:
        return None
    wants_change = bool(
        re.search(r"chang|grow|grew|increas|decreas|drop|fell|compare|\bvs\b|versus|up or down", q)
    )
    if wants_change and period is None:
        period = PlanPeriod(type="last_n_days", n_days=30)
    compare = "none"
    if wants_change:
        year_on_year = re.search(r"year on year|year over year|last year", q)
        compare = "same_period_last_year" if year_on_year else "previous_period"
    ranked = re.search(r"top (\d+)", q)
    ascending = re.search(r"\b(worst|least|lowest|bottom|slowest|quietest)\b", q)
    is_time = group in _TIME_DIMS
    return QueryPlan(
        metric=metric or "revenue",
        group_by=group,
        filter=filters,
        period=period or PlanPeriod(),
        compare=compare,
        sort="chronological" if is_time else ("asc" if ascending else "desc"),
        limit=None if is_time or group is None else int(ranked.group(1)) if ranked else 5,
    )


def _asked_insight(question: str, insights: Sequence[Insight]) -> Insight | None:
    """The insight behind an "Ask AI about this" question, if that's what this is."""
    if not question.lower().startswith(_INSIGHT_PREFIX):
        return None
    headline = question[len(_INSIGHT_PREFIX) :].strip().lower()
    return next((i for i in insights if i.headline.lower() == headline), None)


def answer_offline(
    df: pd.DataFrame,
    question: str,
    currency: str | None,
    insights: Sequence[Insight] = (),
) -> ChatAnswer:
    """Answer with rules alone. Never raises for a question it can't read."""
    ds = DatasetSchema.from_frame(df, currency)
    q = question.lower()

    follow_ups = [f for f in suggestions(ds) if f.lower().rstrip("?") != q.strip().rstrip("?")]

    insight = _asked_insight(question, insights)
    if insight:
        return ChatAnswer(
            answer=f"{insight.headline}. {insight.why_it_matters}",
            how="From the automatic analysis of your data.",
            follow_ups=follow_ups,
            plan=None,
            result=None,
            chart=insight.chart,
            source="offline",
        )

    def reply(text: str, answerable: bool = False) -> ChatAnswer:
        return ChatAnswer(
            answer=text,
            how=None,
            follow_ups=follow_ups,
            plan=None,
            result=None,
            chart=None,
            source="offline",
            answerable=answerable,
        )

    missing = _MISSING.search(q)
    if missing and _metric(q, ds) not in ("profit", "cost"):
        return reply(f"I can't work out {missing.group(1)} from this file; it only records sales.")
    plan = build_plan(question, df, ds)
    if plan is None:
        return reply(_NOT_UNDERSTOOD)
    try:
        plan = validate_plan(plan, df, ds)
    except PlanError as exc:
        return reply(str(exc))
    result = run_plan(df, plan, ds)
    answer = template_answer(result)
    if plan.metric == "profit" and "margin" in q and result.source_rows:
        revenue = run_plan(df, plan.model_copy(update={"metric": "revenue"}), ds).total
        if revenue:
            answer += f" That is a {result.total / revenue * 100:.1f}% margin on revenue."
    return ChatAnswer(
        answer=answer,
        how=describe(plan, result),
        follow_ups=follow_ups,
        plan=plan.model_dump(),
        result=result,
        chart=chart_for(plan, result),
        source="offline",
    )
