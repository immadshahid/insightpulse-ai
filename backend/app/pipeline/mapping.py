"""Column-role mapping.

A :class:`ColumnMapper` turns a profile + 5 sample rows into a role mapping.
Phase 1 ships :class:`HeuristicMapper` (name keywords + column kinds).
Phase 3 adds an LLM mapper implementing the same protocol.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.pipeline.profiler import ColumnProfile, DatasetProfile

Role = Literal["date", "revenue", "quantity", "product", "customer", "region", "order_id"]
ROLES: tuple[Role, ...] = (
    "date",
    "revenue",
    "quantity",
    "product",
    "customer",
    "region",
    "order_id",
)
REQUIRED_ROLES: tuple[Role, ...] = ("date", "revenue")


class ColumnMapping(BaseModel):
    """Role -> source column name (None when the dataset has no such column)."""

    date: str | None = None
    revenue: str | None = None
    quantity: str | None = None
    product: str | None = None
    customer: str | None = None
    region: str | None = None
    order_id: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source: Literal["heuristic", "llm", "user"] = "heuristic"

    def assigned(self) -> dict[str, str]:
        """Only the roles that have a column."""
        return {r: getattr(self, r) for r in ROLES if getattr(self, r)}


class MappingError(ValueError):
    """Raised when a mapping is invalid for a dataset."""


class ColumnMapper(Protocol):
    """Anything that can propose a column mapping."""

    def map_columns(
        self, profile: DatasetProfile, samples: list[dict[str, str]]
    ) -> ColumnMapping: ...


# Keyword weights per role; earlier keywords are stronger signals.
_KEYWORDS: dict[Role, list[tuple[str, float]]] = {
    "date": [
        ("order date", 1.0),
        ("date", 0.9),
        ("timestamp", 0.9),
        ("created", 0.7),
        ("time", 0.6),
        ("day", 0.4),
    ],
    "revenue": [
        ("revenue", 1.0),
        ("total", 0.9),
        ("sales", 0.9),
        ("amount", 0.85),
        ("net", 0.6),
        ("gmv", 0.9),
        ("value", 0.5),
        ("price", 0.3),
    ],
    "quantity": [("quantity", 1.0), ("qty", 1.0), ("units", 0.9), ("count", 0.5), ("items", 0.6)],
    "product": [("product", 1.0), ("item", 0.8), ("sku", 0.8), ("category", 0.5), ("title", 0.4)],
    "customer": [
        ("customer id", 1.0),
        ("customer", 0.9),
        ("client", 0.8),
        ("buyer", 0.8),
        ("user", 0.5),
        ("email", 0.4),
    ],
    "region": [
        ("city", 1.0),
        ("region", 0.95),
        ("state", 0.8),
        ("province", 0.9),
        ("country", 0.7),
        ("area", 0.6),
        ("store", 0.5),
        ("branch", 0.6),
    ],
    "order_id": [
        ("order id", 1.0),
        ("order no", 1.0),
        ("invoice", 0.9),
        ("order", 0.6),
        ("transaction", 0.8),
        ("receipt", 0.8),
    ],
}
_KIND_FIT: dict[Role, set[str]] = {
    "date": {"datetime"},
    "revenue": {"numeric"},
    "quantity": {"numeric"},
    "product": {"categorical", "text"},
    "customer": {"identifier", "categorical", "text"},
    "region": {"categorical", "text"},  # a chain can have hundreds of cities
    "order_id": {"identifier", "text", "categorical"},
}
_PENALTIES: dict[Role, list[str]] = {
    "revenue": ["unit", "discount", "%", "qty", "id"],
    "customer": ["name", "phone", "email"],
    "product": ["id"],
}


def _norm(name: str) -> str:
    return re.sub(r"[_\-]+", " ", name.lower()).strip()


def _score(role: Role, col: ColumnProfile) -> float:
    name = _norm(col.name)
    kw = max((w for k, w in _KEYWORDS[role] if k in name), default=0.0)
    if kw == 0:
        return 0.0
    # A strong name match survives messy values (the cleaner reports the bad rows).
    fit = 1.0 if col.kind in _KIND_FIT[role] else (0.5 if kw >= 0.85 else 0.25)
    penalty = 0.5 if any(p in name for p in _PENALTIES.get(role, [])) else 1.0
    if role == "customer" and "id" in name:
        penalty = 1.0  # "Customer ID" beats "Customer Name"
    return kw * fit * penalty


class HeuristicMapper:
    """Rule-based mapper using column names and inferred kinds."""

    def map_columns(self, profile: DatasetProfile, samples: list[dict[str, str]]) -> ColumnMapping:
        """Assign each role its best-scoring column, never reusing a column."""
        candidates = sorted(
            ((_score(role, col), role, col.name) for role in ROLES for col in profile.columns),
            reverse=True,
        )
        used_cols: set[str] = set()
        result: dict[str, str] = {}
        confidence: dict[str, float] = {}
        for score, role, col_name in candidates:
            if score < 0.3 or role in result or col_name in used_cols:
                continue
            result[role] = col_name
            confidence[role] = round(min(score, 1.0), 2)
            used_cols.add(col_name)
        return ColumnMapping(**result, confidence=confidence, source="heuristic")


def validate_mapping(mapping: ColumnMapping, columns: list[str]) -> None:
    """Raise :class:`MappingError` if roles are missing, unknown or duplicated."""
    assigned = mapping.assigned()
    missing = [r for r in REQUIRED_ROLES if r not in assigned]
    if missing:
        raise MappingError(f"Choose a column for: {', '.join(missing)}.")
    unknown = [c for c in assigned.values() if c not in columns]
    if unknown:
        raise MappingError(f"Unknown column(s): {', '.join(unknown)}.")
    values = list(assigned.values())
    dupes = {c for c in values if values.count(c) > 1}
    if dupes:
        raise MappingError(f"A column can only have one role: {', '.join(sorted(dupes))}.")
