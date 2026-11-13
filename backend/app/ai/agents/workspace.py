"""The data an agent may touch: privacy-safe copies of one dataset, and an evidence ledger.

Nothing here reaches the application database or the file system. Each dataset gets
* a throwaway in-memory SQLite database holding one ``sales`` table (the clean data), and
* a sanitised DataFrame of the file as uploaded, including columns the dashboards ignore.

Customers are replaced by aliases and personal columns removed *before* either copy is
made, so no tool can return them. The alias table is local and restores names at the end.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.ai.privacy import Pseudonymizer, mask_text
from app.pipeline.cleaner import is_pii_column
from app.pipeline.parsing import looks_numeric, parse_dates, parse_numeric

MAX_ROWS = 200
SQL_SECONDS = 3.0
TABLE = "sales"
GENERAL_TABLE = "data"

_ALLOWED_SQL_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


class ToolInputError(ValueError):
    """The agent asked for something invalid; the message goes back to it to correct."""


def jsonable_value(value: Any) -> Any:
    """Plain JSON value for one cell."""
    if value is None or (not isinstance(value, (list, dict, str)) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    return round(value, 4) if isinstance(value, float) else value


def frame_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame to JSON-safe rows."""
    return [
        {str(k): jsonable_value(v) for k, v in row.items()} for row in df.to_dict(orient="records")
    ]


def _mask_strings(series: pd.Series) -> pd.Series:
    """Mask contact details in a text column (each distinct value once)."""
    uniques = series.dropna().unique()
    return series.map({v: mask_text(str(v)) for v in uniques})


def _is_text(series: pd.Series) -> bool:
    return not (
        pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series)
    )


def _sanitise_clean(clean: pd.DataFrame, pseudo: Pseudonymizer) -> pd.DataFrame:
    df = clean.drop(columns=[c for c in clean.columns if c != "customer" and is_pii_column(c)])
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif col == "customer":
            df[col] = df[col].map(lambda v: pseudo.alias(v) if pd.notna(v) else None)
        elif _is_text(df[col]):
            df[col] = _mask_strings(df[col].astype("object"))
    return df


def _sanitise_raw(
    raw: pd.DataFrame, mapping: dict[str, Any], pseudo: Pseudonymizer
) -> pd.DataFrame:
    customer_col, date_col = mapping.get("customer"), mapping.get("date")
    df = raw.drop(columns=[c for c in raw.columns if c != customer_col and is_pii_column(str(c))])
    for col in df.columns:
        if col == customer_col:
            df[col] = df[col].map(lambda v: pseudo.alias(str(v).strip()) if pd.notna(v) else None)
        elif col == date_col:
            df[col] = parse_dates(df[col])
        elif _is_text(df[col]):
            present = df[col].dropna()
            if len(present) and looks_numeric(present).mean() >= 0.9:
                df[col] = parse_numeric(df[col])
            else:
                df[col] = _mask_strings(df[col].astype("object"))
    return df


class SqlSandbox:
    """Read-only, time-limited SQL over a private in-memory copy of the clean data."""

    def __init__(self, df: pd.DataFrame, table: str = "sales") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        df.to_sql(table, self._conn, index=False)
        self._schema = [(r[1], r[2]) for r in self._conn.execute(f"PRAGMA table_info({table})")]
        self._conn.execute("PRAGMA query_only=ON")
        self._conn.set_authorizer(self._authorize)

    @staticmethod
    def _authorize(action: int, arg1: Any, arg2: Any, _db: Any, _trigger: Any) -> int:
        if action not in _ALLOWED_SQL_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() == "load_extension":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @property
    def schema(self) -> list[tuple[str, str]]:
        """(column, SQL type) pairs of the sales table."""
        return self._schema

    def query(self, sql: str) -> tuple[list[dict[str, Any]], bool]:
        """Run one SELECT. Returns (rows, truncated)."""
        statement = sql.strip().rstrip(";").strip()
        lowered = statement.lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise ToolInputError("Only a single SELECT (or WITH ... SELECT) statement is allowed.")
        if ";" in statement:
            raise ToolInputError("Send one statement at a time, without semicolons.")
        ends_at = time.monotonic() + SQL_SECONDS
        with self._lock:
            self._conn.set_progress_handler(lambda: int(time.monotonic() > ends_at), 10_000)
            try:
                cursor = self._conn.execute(statement)
                columns = [c[0] for c in cursor.description]
                fetched = cursor.fetchmany(MAX_ROWS + 1)
            except sqlite3.Error as exc:
                raise ToolInputError(f"SQL error: {exc}") from exc
            finally:
                self._conn.set_progress_handler(None, 0)
        rows = [{c: jsonable_value(v) for c, v in zip(columns, r, strict=True)} for r in fetched]
        return rows[:MAX_ROWS], len(rows) > MAX_ROWS


@dataclass
class Workspace:
    """Everything the agents can see for one dataset version."""

    sql: SqlSandbox
    csv: pd.DataFrame
    pseudo: Pseudonymizer
    real_customers: list[str]
    currency: str | None
    date_min: str | None
    date_max: str | None
    # Cleaned field -> the uploaded column it came from, e.g. {"region": "City"}.
    field_sources: dict[str, str] = field(default_factory=dict)
    # "sales" (table `sales` of order lines) or "general" (table `data`, any table).
    kind: str = "sales"
    table: str = TABLE

    def describe_fields(self) -> str:
        """One line naming the original column behind each cleaned field."""
        return ", ".join(f"{k} = file column '{v}'" for k, v in self.field_sources.items())


_ROLES = ("date", "revenue", "quantity", "product", "customer", "region", "order_id")


def build_workspace(
    clean: pd.DataFrame,
    raw: pd.DataFrame,
    mapping: dict[str, Any],
    currency: str | None,
    kind: str = "sales",
) -> Workspace:
    """Create the sanitised copies. Aliases are shared by the SQL and CSV views."""
    pseudo = Pseudonymizer()
    safe_clean = _sanitise_clean(clean, pseudo)
    if kind == "general":
        table = GENERAL_TABLE
        sources: dict[str, str] = {}
        has_dates = False
        safe_raw = safe_clean  # the typed table is the file, minus personal columns
    else:
        table = TABLE
        sources = {
            r: str(mapping[r]) for r in _ROLES if isinstance(mapping.get(r), str) and r in clean
        }
        has_dates = "date" in clean
        safe_raw = _sanitise_raw(raw, mapping, pseudo)
    return Workspace(
        sql=SqlSandbox(safe_clean, table),
        csv=safe_raw,
        pseudo=pseudo,
        real_customers=list(pseudo.forward),
        currency=currency,
        date_min=str(clean["date"].min().date()) if has_dates else None,
        date_max=str(clean["date"].max().date()) if has_dates else None,
        field_sources=sources,
        kind=kind,
        table=table,
    )


@dataclass
class Evidence:
    """One tool result that a final answer may quote."""

    id: str
    agent: str
    title: str
    rows: list[dict[str, Any]]
    detail: str | None = None


@dataclass
class Ledger:
    """Per-question record of evidence and of the steps shown to the user."""

    evidence: dict[str, Evidence] = field(default_factory=dict)
    steps: list[dict[str, str]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, agent: str, title: str, rows: list[dict[str, Any]], detail: str | None) -> str:
        """Store a result and return its evidence id."""
        with self._lock:
            eid = f"E{len(self.evidence) + 1}"
            self.evidence[eid] = Evidence(eid, agent, title, rows, detail)
            return eid

    def step(self, agent: str, summary: str, detail: str | None = None) -> None:
        """Record a step for the "How I got this" panel."""
        with self._lock:
            self.steps.append({"agent": agent, "summary": summary, "detail": detail or ""})

    def add_source(self, title: str, text: str) -> None:
        """Remember a retrieved passage once."""
        with self._lock:
            if all(s["title"] != title for s in self.sources):
                self.sources.append({"title": title, "text": text})

    def grounding_pool(self) -> list[Any]:
        """All data the final answer may draw numbers from."""
        with self._lock:
            return [e.rows for e in self.evidence.values()] + [s["text"] for s in self.sources]
