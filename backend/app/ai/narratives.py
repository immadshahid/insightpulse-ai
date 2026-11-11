"""Plain-language narratives written ONLY from computed JSON.

* Insight narratives: 2-3 sentences per insight from that insight's JSON.
* Dashboard summary: 2-3 sentences from the period KPI cards and top insights.

Each text is checked by the number guardrail; anything with an unsupported number is
dropped and the template text is used instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.client import LLMClient, LLMError
from app.ai.grounding import ungrounded_numbers
from app.insights.base import Insight

log = logging.getLogger(__name__)

STYLE = """Write for a busy small-business owner in Pakistan: plain words, no jargon,
no emoji, no markdown. Use ONLY facts and numbers present in the JSON you are given;
never estimate, invent or recompute a number. Round money compactly (e.g. PKR 1.2M,
PKR 45K) and percentages to whole numbers or one decimal. If the JSON does not support
a claim, leave it out."""

NARRATIVE_SYSTEM = f"""You explain analytics findings. For each insight, write 2-3
sentences: what happened, why it matters, and (if the data supports it) what to watch.
{STYLE}"""

SUMMARY_SYSTEM = f"""You write the 2-3 sentence summary at the top of a sales dashboard
for the selected period: the headline revenue movement, the most important driver or
risk from the insights, and one thing to look at. {STYLE}"""

_MAX_LIST = 12


def compact(data: Any, max_list: int = _MAX_LIST) -> Any:
    """Shorten long lists (e.g. cohort matrices) so prompts stay small and focused."""
    if isinstance(data, dict):
        return {k: compact(v, max_list) for k, v in data.items()}
    if isinstance(data, list):
        items = [compact(v, max_list) for v in data[:max_list]]
        return items + ([f"... {len(data) - max_list} more"] if len(data) > max_list else [])
    return data


def insight_payload(insight: Insight) -> dict[str, Any]:
    """What the LLM may see for one insight (no chart payloads)."""
    return {
        "id": insight.id,
        "tag": insight.tag,
        "headline": insight.headline,
        "why_it_matters": insight.why_it_matters,
        "data": compact(insight.data),
    }


NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "narrative": {"type": "string"}},
                "required": ["id", "narrative"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def write_narratives(llm: LLMClient, insights: list[Insight]) -> dict[str, str]:
    """``{insight_id: narrative}`` for every insight whose narrative passes the guardrail."""
    if not insights:
        return {}
    payloads = {i.id: insight_payload(i) for i in insights}
    data = llm.complete_json(
        task="insight_narratives",
        system=NARRATIVE_SYSTEM,
        user="Insights JSON:\n"
        + json.dumps(list(payloads.values()), ensure_ascii=False, default=str),
        schema=NARRATIVE_SCHEMA,
        effort="low",
        max_tokens=6000,
    )
    out: dict[str, str] = {}
    for item in data.get("items", []):
        iid, text = item.get("id"), (item.get("narrative") or "").strip()
        if iid not in payloads or not text:
            continue
        bad = ungrounded_numbers(text, payloads[iid])
        if bad:
            log.warning("Dropped narrative for %s: unsupported numbers %s", iid, bad)
            continue
        out[iid] = text
    return out


def write_summary(
    llm: LLMClient,
    period_label: str,
    kpis: list[dict[str, Any]],
    insights: list[Insight],
    currency: str | None,
) -> str | None:
    """Dashboard summary, or None if the LLM fails or the text is not grounded."""
    source = {
        "period": period_label,
        "currency": currency,
        "kpis": kpis,
        "top_insights": [insight_payload(i) for i in insights[:3]],
    }
    try:
        data = llm.complete_json(
            task="dashboard_summary",
            system=SUMMARY_SYSTEM,
            user="Dashboard JSON:\n" + json.dumps(source, ensure_ascii=False, default=str),
            schema=SUMMARY_SCHEMA,
            effort="low",
            max_tokens=1500,
        )
    except LLMError as exc:
        log.info("Dashboard summary fell back to template: %s", exc)
        return None
    text = (data.get("summary") or "").strip()
    bad = ungrounded_numbers(text, source)
    if not text or bad:
        log.warning("Dropped dashboard summary: unsupported numbers %s", bad)
        return None
    return text
