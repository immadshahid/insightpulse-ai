"""AI column mapping: column names + 5 masked sample rows -> role mapping.

Implements the same ``ColumnMapper`` protocol as the heuristic mapper. The schema only
allows real column names (or null) for each role, the result is validated, and any
failure or invalid answer falls back to the heuristic mapping.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.client import LLMClient, LLMError
from app.ai.privacy import mask_sample_rows
from app.pipeline.mapping import (
    ROLES,
    ColumnMapping,
    HeuristicMapper,
    MappingError,
    validate_mapping,
)
from app.pipeline.profiler import DatasetProfile

log = logging.getLogger(__name__)

SYSTEM = """You map the columns of a small business's sales export to analysis roles.
Roles:
- date: when the order/sale happened
- revenue: money received for the row (a total/amount, not a unit price or discount)
- quantity: number of units
- product: product or item name/category
- customer: a stable customer identifier (prefer an ID column over a name column)
- region: city, region, branch or store
- order_id: order / invoice / transaction identifier
Use each column at most once. Use null when no column fits a role.
Give a confidence from 0 to 1 for each role you assign."""


def mapping_schema(columns: list[str]) -> dict[str, Any]:
    """JSON schema allowing only real column names (or null) for each role."""
    choice = {"anyOf": [{"type": "string", "enum": columns}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "mapping": {
                "type": "object",
                "properties": {r: choice for r in ROLES},
                "required": list(ROLES),
                "additionalProperties": False,
            },
            "confidence": {
                "type": "object",
                "properties": {r: {"type": "number"} for r in ROLES},
                "required": list(ROLES),
                "additionalProperties": False,
            },
        },
        "required": ["mapping", "confidence"],
        "additionalProperties": False,
    }


def mapping_prompt(columns: list[str], samples: list[dict[str, str]]) -> str:
    """User message: only the column names and up to 5 masked sample rows."""
    rows = mask_sample_rows(samples[:5])
    return (
        f"Columns: {json.dumps(columns, ensure_ascii=False)}\n"
        f"Sample rows (personal data redacted):\n"
        f"{json.dumps(rows, ensure_ascii=False, indent=1)}"
    )


class LLMColumnMapper:
    """Column mapper that asks the LLM, falling back to heuristics on any problem."""

    def __init__(self, llm: LLMClient, fallback: HeuristicMapper | None = None) -> None:
        self.llm = llm
        self.fallback = fallback or HeuristicMapper()

    def map_columns(self, profile: DatasetProfile, samples: list[dict[str, str]]) -> ColumnMapping:
        """Map roles with the LLM; heuristic mapping if it fails or answers badly."""
        heuristic = self.fallback.map_columns(profile, samples)
        if not self.llm.available:
            return heuristic
        columns = profile.column_names()
        try:
            data = self.llm.complete_json(
                task="column_mapping",
                system=SYSTEM,
                user=mapping_prompt(columns, samples),
                schema=mapping_schema(columns),
                effort="low",
                max_tokens=2000,
            )
            raw = {r: data["mapping"].get(r) for r in ROLES}
            conf = {r: round(float(data["confidence"].get(r, 0)), 2) for r in ROLES if raw.get(r)}
            mapping = ColumnMapping(**raw, confidence=conf, source="llm")
            validate_mapping(mapping, columns)
            return mapping
        except (LLMError, MappingError, KeyError, TypeError, ValueError) as exc:
            log.info("LLM column mapping not used (%s); using heuristics", exc)
            return heuristic
