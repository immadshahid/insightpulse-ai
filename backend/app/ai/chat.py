"""Ask-AI: question -> JSON plan -> validate -> pandas -> chart -> grounded answer.

Two LLM calls per question:
1. Planner: masked question + dataset description -> QueryPlan (schema-constrained).
2. Writer: question + computed result JSON -> 2-4 sentence answer + 3 follow-ups,
   checked by the number guardrail (falls back to a template answer).

Customer identifiers are pseudonymised in both directions; emails/phones are masked.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import ValidationError

from app.ai.client import LLMClient, LLMError
from app.ai.grounding import ungrounded_numbers
from app.ai.narratives import STYLE
from app.ai.privacy import Pseudonymizer, mask_text
from app.ai.query import (
    DatasetSchema,
    PlanError,
    QueryPlan,
    QueryResult,
    chart_for,
    describe,
    plan_schema,
    run_plan,
    template_answer,
    validate_plan,
)
from app.insights.base import ChartSpec, has

log = logging.getLogger(__name__)
MAX_HISTORY_TURNS = 6

PLANNER_SYSTEM = """You turn a business owner's question about their sales data into a
query plan (JSON). You do not answer the question and you never write code.

Rules:
- Pick the metric and optional breakdown (group_by) that answer the question.
- "period" is relative to the LAST DATE IN THE DATA (given below), not today's date.
  "last month" = the latest complete calendar month in the data; "this month" = the
  month of the last date; "last week" = last_n_days 7; "this year" = between Jan 1 of the
  last date's year and the last date.
- Use filters for specific products, regions, customers, months or weekdays mentioned.
- Use compare="previous_period" when the question asks about change, growth or
  "vs before"; "same_period_last_year" for year-on-year.
- For "top/best/most" use sort desc and a limit (default 5); "worst/least" sort asc.
- If the data cannot answer (e.g. profit, costs, marketing spend, stock levels, anything
  not in the listed metrics/dimensions), set answerable=false and explain briefly in
  "reason" what is missing. Still fill the other fields with defaults.
- Customers appear as aliases like "Customer 3"; keep them exactly as written."""

WRITER_SYSTEM = f"""You answer a business owner's question using ONLY the computed
result JSON. Write 2-4 sentences: the direct answer first, then the most useful detail
(biggest item, change vs comparison) if present. {STYLE}
Then suggest 3 short follow-up questions (under 10 words each) that this same data can
answer, using its metrics and breakdowns."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "follow_ups"],
    "additionalProperties": False,
}


@dataclass
class ChatTurn:
    """One prior message in the conversation (sent by the app)."""

    role: str
    content: str


@dataclass
class ChatAnswer:
    """What the API returns for a question."""

    answer: str
    how: str | None
    follow_ups: list[str]
    plan: dict[str, Any] | None
    result: QueryResult | None
    chart: ChartSpec | None
    source: str
    answerable: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def describe_dataset(df: pd.DataFrame, ds: DatasetSchema) -> str:
    """What the planner may know: metrics, breakdowns, sample category values, dates."""
    lines = [
        f"Last date in the data: {ds.date_max.date()} (first: {ds.date_min.date()}).",
        f"Currency: {ds.currency or 'unknown'}.",
        f"Metrics: {', '.join(ds.metrics)}.",
        f"Breakdowns (group_by): {', '.join(ds.dimensions)}.",
        f"Months available: {df['month'].min()} to {df['month'].max()}.",
    ]
    for col in ("product", "region"):
        if has(df, col):
            top = df[col].value_counts().index[:25].tolist()
            lines.append(f"{col} values: {', '.join(map(str, top))}.")
    if has(df, "customer"):
        lines.append(
            "customer values are private; refer to them only by the aliases used "
            "in the question."
        )
    return "\n".join(lines)


def suggestions(ds: DatasetSchema) -> list[str]:
    """Generic follow-ups this dataset can answer (used when the LLM gives none)."""
    out = ["How did revenue change over the last 30 days?"]
    if "product" in ds.dimensions:
        out.append("Which products sold the most last month?")
    if "region" in ds.dimensions:
        out.append("Which city brings in the most revenue?")
    out.append("Which weekday is busiest?")
    return out[:3]


def _history_text(history: list[ChatTurn], pseudo: Pseudonymizer, known: list[str]) -> str:
    turns = history[-MAX_HISTORY_TURNS:]
    return "\n".join(f"{t.role}: {pseudo.mask_known(mask_text(t.content), known)}" for t in turns)


def _alias_result(result: QueryResult, pseudo: Pseudonymizer) -> dict[str, Any]:
    data = result.model_dump()
    if result.group_by == "customer":
        for row in data["rows"]:
            row["label"] = pseudo.alias(row["label"])
    return data


def ask(
    llm: LLMClient,
    df: pd.DataFrame,
    question: str,
    currency: str | None,
    history: list[ChatTurn] | None = None,
) -> ChatAnswer:
    """Answer one question. Raises LLMError if the planner itself is unavailable."""
    ds = DatasetSchema.from_frame(df, currency)
    pseudo = Pseudonymizer()
    known = df["customer"].dropna().astype(str).unique().tolist() if has(df, "customer") else []
    safe_q = pseudo.mask_known(mask_text(question.strip()), known)
    hist = _history_text(history or [], pseudo, known)

    user = (
        f"Dataset:\n{describe_dataset(df, ds)}\n\n"
        + (f"Conversation so far:\n{hist}\n\n" if hist else "")
        + f"Question: {safe_q}"
    )
    raw = llm.complete_json(
        task="chat_plan",
        system=PLANNER_SYSTEM,
        user=user,
        schema=plan_schema(ds),
        effort="medium",
        max_tokens=3000,
    )
    try:
        plan = QueryPlan.model_validate(raw)
    except ValidationError as exc:
        raise LLMError("The AI returned an invalid query plan.") from exc

    if not plan.answerable:
        reason = pseudo.restore((plan.reason or "").strip())
        msg = "I can't answer that from this data."
        return ChatAnswer(
            answer=f"{msg} {reason}".strip(),
            how=None,
            follow_ups=suggestions(ds),
            plan=plan.model_dump(),
            result=None,
            chart=None,
            source="llm",
            answerable=False,
        )

    # Restore aliases in filters before matching against real values.
    for f in plan.filter:
        f.values = [pseudo.restore(v) for v in f.values]
    try:
        plan = validate_plan(plan, df, ds)
    except PlanError as exc:
        return ChatAnswer(
            answer=str(exc),
            how=None,
            follow_ups=suggestions(ds),
            plan=plan.model_dump(),
            result=None,
            chart=None,
            source="llm",
            answerable=False,
        )

    result = run_plan(df, plan, ds)
    how = describe(plan, result)
    chart = chart_for(plan, result)
    answer, follow_ups, source = template_answer(result), suggestions(ds), "template"

    aliased = _alias_result(result, pseudo)
    writer_input = {
        "question": safe_q,
        "how_computed": pseudo.mask_known(how, known),
        "result": aliased,
    }
    try:
        data = llm.complete_json(
            task="chat_answer",
            system=WRITER_SYSTEM,
            user=json.dumps(writer_input, ensure_ascii=False, default=str),
            schema=ANSWER_SCHEMA,
            effort="low",
            max_tokens=2000,
        )
        text = (data.get("answer") or "").strip()
        bad = ungrounded_numbers(text, writer_input)
        if text and not bad:
            answer, source = pseudo.restore(text), "llm"
        elif bad:
            log.warning("Chat answer dropped: unsupported numbers %s", bad)
        ups = [pseudo.restore(u.strip()) for u in data.get("follow_ups", []) if u.strip()]
        if ups:
            follow_ups = [u for u in ups if len(u) <= 90][:3] or follow_ups
    except LLMError as exc:
        log.info("Chat answer writer failed, using template: %s", exc)

    return ChatAnswer(
        answer=answer,
        how=how,
        follow_ups=follow_ups,
        plan=plan.model_dump(),
        result=result,
        chart=chart,
        source=source,
    )
