"""A scriptable stand-in for the LLM that records every request."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.ai.client import LLMError

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class FakeLLM:
    """Returns whatever the per-task handler returns; raises LLMError if none."""

    available = True
    model = "fake-model"

    def __init__(self, handlers: dict[str, Handler] | None = None) -> None:
        self.handlers = handlers or {}
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: str = "low",
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        call = {
            "task": task,
            "system": system,
            "user": user,
            "schema": schema,
            "effort": effort,
            "max_tokens": max_tokens,
        }
        self.calls.append(call)
        handler = self.handlers.get(task)
        if handler is None:
            raise LLMError(f"no fake handler for {task}")
        result = handler(call)
        if isinstance(result, Exception):
            raise result
        return result

    def sent_text(self) -> str:
        """Everything that would have been sent to the provider."""
        return "\n".join(c["system"] + "\n" + c["user"] for c in self.calls)


def json_after(prefix: str, user: str) -> Any:
    """Parse the JSON that follows ``prefix`` in a prompt."""
    return json.loads(user.split(prefix, 1)[1])


def echo_narratives(call: dict[str, Any]) -> dict[str, Any]:
    """Narrative = the insight's own headline (always grounded)."""
    items = json_after("Insights JSON:\n", call["user"])
    return {"items": [{"id": i["id"], "narrative": i["headline"] + "."} for i in items]}


def echo_summary(call: dict[str, Any]) -> dict[str, Any]:
    """Summary built from the first KPI's display string."""
    data = json_after("Dashboard JSON:\n", call["user"])
    k = data["kpis"][0]
    return {"summary": f"{k['label']} was {k['display']} over the {data['period']}."}


def echo_answer(call: dict[str, Any]) -> dict[str, Any]:
    """Chat answer quoting the top row's label and raw value."""
    data = json.loads(call["user"])
    rows = data["result"]["rows"]
    text = f"Total was {data['result']['total']}."
    if rows:
        text += f" {rows[0]['label']} came first with {rows[0]['value']}."
    return {
        "answer": text,
        "follow_ups": [
            "Which products sold most?",
            "How about last month?",
            "Which city grew fastest?",
        ],
    }


def plan(**overrides: Any) -> Handler:
    """Planner handler returning a fixed plan (defaults filled in)."""
    base = {
        "answerable": True,
        "reason": None,
        "metric": "revenue",
        "group_by": None,
        "filter": [],
        "period": {"type": "all", "n_days": None, "month": None, "start": None, "end": None},
        "compare": "none",
        "sort": "desc",
        "limit": None,
        "chart": "auto",
    }
    base.update(overrides)
    return lambda _call: base
