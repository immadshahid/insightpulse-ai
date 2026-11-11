"""The agent loop: call Claude, run the tools it asks for, repeat until it answers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.ai.agents.workspace import ToolInputError
from app.ai.client import Effort, LLMError

log = logging.getLogger(__name__)
MAX_RESULT_CHARS = 20_000


class AgentError(LLMError):
    """The agent could not finish; the caller falls back to the fixed pipeline."""


@dataclass(frozen=True)
class Tool:
    """A function the model may call. Results are returned to it as JSON."""

    name: str
    description: str
    properties: dict[str, Any]
    run: Callable[[dict[str, Any]], Any]

    def definition(self) -> dict[str, Any]:
        """Messages API tool definition (strict: inputs always match the schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.properties),
                "additionalProperties": False,
            },
        }


def _execute(tool: Tool | None, block: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id}
    if tool is None:
        return {**result, "content": f"Unknown tool {block.name}.", "is_error": True}
    try:
        text = json.dumps(tool.run(dict(block.input)), ensure_ascii=False, default=str)
    except ToolInputError as exc:
        return {**result, "content": str(exc), "is_error": True}
    except LLMError:
        raise  # a specialist that cannot finish ends the whole run
    except Exception:  # a broken tool must not end the conversation
        log.exception("Agent tool %s failed", block.name)
        return {**result, "content": "This tool failed. Try another way.", "is_error": True}
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " ...[cut: ask for fewer rows]"
    return {**result, "content": text}


def run_agent(
    llm: Any,
    *,
    name: str,
    system: str,
    user: str,
    tools: list[Tool],
    schema: dict[str, Any],
    effort: Effort,
    max_turns: int,
    deadline: float,
    validate: Callable[[dict[str, Any]], str | None] | None = None,
    max_repairs: int = 1,
) -> dict[str, Any]:
    """Loop until the model returns JSON matching ``schema``.

    ``validate`` may return a correction to send back to the model. The final turn
    disables tools so the run always ends with an answer. Each message is appended
    unchanged, which keeps thinking blocks valid and the prompt cache warm.
    """
    by_name = {t.name: t for t in tools}
    definitions = [t.definition() for t in tools]
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    repairs = 0
    for turn in range(max_turns):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise AgentError(f"{name} ran out of time.")
        response = llm.agent_turn(
            task=name,
            system=system,
            messages=messages,
            tools=definitions,
            schema=schema,
            effort=effort,
            tools_enabled=turn < max_turns - 1,
            timeout=remaining,
        )
        if response.stop_reason == "refusal":
            raise AgentError("The AI declined this request.")
        if response.stop_reason == "max_tokens":
            raise AgentError("The AI response was cut off.")
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        if calls:
            with ThreadPoolExecutor(max_workers=min(len(calls), 3)) as pool:
                results = list(pool.map(lambda b: _execute(by_name.get(b.name), b), calls))
            messages.append({"role": "user", "content": results})
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AgentError("The AI returned malformed JSON.") from exc
        problem = validate(data) if validate else None
        if problem is None:
            return data
        if repairs >= max_repairs or turn == max_turns - 1:
            raise AgentError(f"{name} answer failed validation: {problem}")
        repairs += 1
        messages.append({"role": "user", "content": problem})
    raise AgentError(f"{name} did not finish.")
