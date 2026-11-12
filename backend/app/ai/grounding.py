"""Guardrail: every number in LLM text must come from the data we gave it.

The LLM only sees computed JSON, but it could still invent or mis-copy a figure. We
extract each number from its answer (handling 1.2M, 45K, 12%, 1,234) and require it
to match a number in the source JSON, allowing for rounding and for ratios written as
percentages. Small counting words (1-10), years and day-of-month values are allowed.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:[kKmMbB](?![a-zA-Z])|%)?")
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}


def numbers_in_text(text: str) -> list[tuple[float, str]]:
    """(value, raw token) for each number written in ``text``."""
    out = []
    for match in _NUM_RE.finditer(text):
        raw = match.group(0).strip().rstrip(",")  # "30, 2017": the comma ends the number
        token = raw.replace(",", "").replace(" ", "")
        suffix = token[-1].lower() if token[-1].lower() in "kmb%" else ""
        core = token[:-1] if suffix else token
        try:
            value = float(core)
        except ValueError:
            continue
        if suffix in _SUFFIX:
            value *= _SUFFIX[suffix]
        out.append((value, raw))
    return out


def numbers_in_json(data: Any) -> list[float]:
    """Every numeric value in a JSON-like structure (numbers inside strings too)."""
    found: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            if not (isinstance(node, float) and (math.isnan(node) or math.isinf(node))):
                found.append(float(node))
        elif isinstance(node, str):
            found.extend(v for v, _ in numbers_in_text(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(data)
    return found


def _close(claim: float, source: float, is_pct: bool) -> bool:
    candidates = [source]
    if abs(source) <= 1:
        candidates.append(source * 100)  # a ratio such as 0.234 written as 23%
    for c in candidates:
        tol = max(abs(c) * 0.051, 0.051 if abs(c) < 10 else 0.5)  # rounding to 2 sig figs
        if abs(abs(claim) - abs(c)) <= tol:
            return True
    return False


def ungrounded_numbers(text: str, source: Any) -> list[str]:
    """Numbers in ``text`` that do not match anything in ``source``."""
    pool = numbers_in_json(source if not isinstance(source, str) else json.loads(source))
    bad = []
    for value, raw in numbers_in_text(text):
        if (
            raw.endswith("%") is False
            and float(value).is_integer()
            and (0 <= value <= 10 or 1990 <= value <= 2100 or 1 <= value <= 31 and "," not in raw)
        ):
            continue  # counts, years, days of month
        if not any(_close(value, s, raw.endswith("%")) for s in pool):
            bad.append(raw)
    return bad


def is_grounded(text: str, source: Any) -> bool:
    """True when every number in ``text`` is supported by ``source``."""
    return not ungrounded_numbers(text, source)
