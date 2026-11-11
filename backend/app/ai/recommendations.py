"""Top 3 recommended actions, from insights (+ forecast/churn summaries when available).

The LLM may only use the facts in the JSON it is given; actions with unsupported numbers
are dropped. Without an LLM (or if it fails) rule-based actions are built from the same
insights, so the screen always has something useful.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel

from app.ai.client import LLMClient, LLMError
from app.ai.grounding import ungrounded_numbers
from app.ai.narratives import STYLE, insight_payload
from app.insights.base import Insight, fmt_money

log = logging.getLogger(__name__)
Impact = Literal["high", "medium", "low"]

SYSTEM = f"""You are a practical retail advisor. From the analytics JSON, recommend the
3 most valuable actions the owner can take in the next 2-4 weeks. Each action: a short
imperative title (under 8 words), a 1-2 sentence detail explaining what to do and which
finding it comes from, an impact level, and the ids of the insights it is based on.
Prefer actions that protect revenue (at-risk customers, anomalies) or use clear
opportunities (peak times, top products). {STYLE}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                    "based_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "detail", "impact", "based_on"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["actions"],
    "additionalProperties": False,
}


class Action(BaseModel):
    """One recommended action."""

    title: str
    detail: str
    impact: Impact
    based_on: list[str]


def rule_based(insights: list[Insight], currency: str | None) -> list[Action]:
    """Deterministic actions from insight kinds (no LLM needed)."""
    by_kind = {i.kind: i for i in insights}
    actions: list[Action] = []
    if (i := by_kind.get("rfm_segments")) and i.data.get("at_risk_customers"):
        actions.append(
            Action(
                title="Win back quiet regular customers",
                detail=(
                    f"{i.data['at_risk_customers']:,} customers who used to buy often have "
                    "gone quiet. Send them a personal offer or reminder this week."
                ),
                impact="high",
                based_on=[i.id],
            )
        )
    if i := by_kind.get("anomalies"):
        lead = i.data["anomalies"][0]
        actions.append(
            Action(
                title="Check the unusual sales day",
                detail=(
                    f"{lead['date']} looked very different from normal "
                    f"({fmt_money(lead['revenue'], currency)} vs about "
                    f"{fmt_money(lead['expected'], currency)}). Find out why, and repeat "
                    "it if it was a good promotion."
                ),
                impact="medium",
                based_on=[i.id],
            )
        )
    if i := by_kind.get("weekday_time_pattern"):
        actions.append(
            Action(
                title=f"Plan promotions for {i.data['peak_slot']}",
                detail=(
                    f"{i.data['peak_slot']} is your busiest time. Schedule stock, staff and "
                    f"ads around it, and try a small offer on {i.data['quietest_day']} to "
                    "lift the quietest day."
                ),
                impact="medium",
                based_on=[i.id],
            )
        )
    if i := by_kind.get("top_products"):
        top = i.data["top"][0]["product"]
        actions.append(
            Action(
                title=f"Keep {top} well stocked",
                detail=(
                    f"{top} is your biggest seller. Avoid stock-outs and feature it in "
                    "bundles with slower products."
                ),
                impact="medium",
                based_on=[i.id],
            )
        )
    if (i := by_kind.get("cohort_retention")) and i.data.get("month1_retention", 1) < 0.3:
        actions.append(
            Action(
                title="Follow up with first-time buyers",
                detail="Few new customers buy again next month. A thank-you message with a "
                "small second-order discount can lift repeat purchases.",
                impact="medium",
                based_on=[i.id],
            )
        )
    return actions[:3]


def recommend(
    llm: LLMClient,
    insights: list[Insight],
    currency: str | None,
    extras: dict[str, Any] | None = None,
) -> tuple[list[Action], str]:
    """``(actions, source)`` where source is 'llm' or 'rules'."""
    fallback = rule_based(insights, currency)
    if not llm.available or not insights:
        return fallback, "rules"
    source = {
        "currency": currency,
        "insights": [insight_payload(i) for i in insights[:8]],
        **(extras or {}),
    }
    ids = {i.id for i in insights}
    try:
        data = llm.complete_json(
            task="recommendations",
            system=SYSTEM,
            user="Analytics JSON:\n" + json.dumps(source, ensure_ascii=False, default=str),
            schema=SCHEMA,
            effort="medium",
            max_tokens=3000,
        )
    except LLMError as exc:
        log.info("Recommendations fell back to rules: %s", exc)
        return fallback, "rules"
    actions = []
    for raw in data.get("actions", []):
        try:
            action = Action.model_validate(raw)
        except ValueError:
            continue
        bad = ungrounded_numbers(f"{action.title} {action.detail}", source)
        if bad:
            log.warning("Dropped recommendation with unsupported numbers %s", bad)
            continue
        action.based_on = [b for b in action.based_on if b in ids]
        actions.append(action)
    if not actions:
        return fallback, "rules"
    return actions[:3], "llm"
