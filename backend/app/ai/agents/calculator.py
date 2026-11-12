"""A safe calculator tool, so derived figures (percentages, differences) are checkable.

The answer guardrail only accepts numbers that appear in a tool result. When the model
works out a margin or a percentage change itself, the figure is right but unprovable;
routing the arithmetic through this tool puts the result on the record. Only numbers,
+ - * / and brackets are accepted, evaluated from the syntax tree (no eval).
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from app.ai.agents.workspace import Ledger, ToolInputError

MAX_EXPRESSIONS = 12
MAX_LENGTH = 200
_BINARY: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def evaluate(expression: str) -> float:
    """Value of an arithmetic expression such as ``(118448 - 79412) / 79412 * 100``."""
    text = expression.replace(",", "").strip()
    if not text or len(text) > MAX_LENGTH:
        raise ToolInputError("Give a short arithmetic expression.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ToolInputError(f"Could not read the expression: {expression}") from exc

    def value(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](value(node.left), value(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            inner = value(node.operand)
            return -inner if isinstance(node.op, ast.USub) else inner
        raise ToolInputError("Only numbers, + - * / and brackets are allowed.")

    try:
        return value(tree)
    except ZeroDivisionError as exc:
        raise ToolInputError(f"Division by zero in: {expression}") from exc


def calculate(ledger: Ledger, args: dict[str, Any]) -> dict[str, Any]:
    """Run each labelled expression and record the results as evidence."""
    items = args["calculations"][:MAX_EXPRESSIONS]
    rows = [
        {
            "label": item["label"],
            "expression": item["expression"],
            "result": round(evaluate(item["expression"]), 4),
        }
        for item in items
    ]
    summary = "; ".join(r["label"] for r in rows) or "calculation"
    detail = "\n".join(f"{r['expression']} = {r['result']}" for r in rows)
    eid = ledger.add("calculator", "Calculations", rows, detail)
    ledger.step("calculator", summary, detail)
    return {"evidence_id": eid, "results": rows}


CALCULATIONS_SCHEMA = {
    "calculations": {
        "type": "array",
        "description": "Each item: a short label and an arithmetic expression to evaluate.",
        "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "expression": {"type": "string"},
            },
            "required": ["label", "expression"],
            "additionalProperties": False,
        },
    }
}
