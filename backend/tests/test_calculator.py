"""Calculator tool and grounding of derived figures."""

from __future__ import annotations

import pytest

from app.ai.agents.calculator import calculate, evaluate
from app.ai.agents.workspace import Ledger, ToolInputError
from app.ai.grounding import ungrounded_numbers


def test_arithmetic() -> None:
    assert evaluate("(118,448 - 79,412) / 79412 * 100") == pytest.approx(49.155, rel=1e-4)
    assert evaluate("-2 + 3 * 4") == 10


@pytest.mark.parametrize(
    "expr",
    ["__import__('os').system('x')", "2 ** 999999", "abs(-1)", "a + 1", "1 / 0", "", "1" * 300],
)
def test_anything_but_plain_arithmetic_is_refused(expr: str) -> None:
    with pytest.raises(ToolInputError):
        evaluate(expr)


def test_results_become_evidence_the_answer_can_quote() -> None:
    ledger = Ledger()
    ledger.add("sql", "Nov revenue", [{"y2016": 79412, "y2017": 118448}], None)
    answer = "November revenue rose 49.2% to 118,448."
    assert ungrounded_numbers(answer, ledger.grounding_pool()) == ["49.2%"]
    out = calculate(
        ledger,
        {"calculations": [{"label": "Nov change", "expression": "(118448-79412)/79412*100"}]},
    )
    assert out["results"][0]["result"] == pytest.approx(49.1551, rel=1e-4)
    assert ungrounded_numbers(answer, ledger.grounding_pool()) == []
    assert ledger.steps[-1]["agent"] == "calculator"


def test_a_trailing_comma_does_not_hide_a_day_of_month() -> None:
    assert ungrounded_numbers("Sales peaked on November 30, 2017.", [{"x": 1}]) == []


def test_calculator_steps_fit_the_api_response() -> None:
    from app.schemas import AgentStepOut

    ledger = Ledger()
    calculate(ledger, {"calculations": [{"label": "share", "expression": "1 / 4 * 100"}]})
    assert [AgentStepOut(**s).agent for s in ledger.steps] == ["calculator"]


def test_charts_with_placeholder_labels_are_left_out() -> None:
    from app.ai.agents.orchestrator import build_chart
    from app.ai.privacy import Pseudonymizer

    ledger = Ledger()
    eid = ledger.add("sql", "periods", [{"p": "A", "v": 10.6}, {"p": "B", "v": 10.5}], None)
    spec = {
        "evidence_id": eid,
        "label_column": "p",
        "value_column": "v",
        "is_money": True,
        "kind": "bar",
    }
    assert build_chart(spec, ledger, Pseudonymizer()) == (None, None)
    ledger.evidence[eid].rows = [{"p": "Sep 2026", "v": 10.5}, {"p": "Oct 2026", "v": 10.6}]
    assert build_chart(spec, ledger, Pseudonymizer())[0] is not None


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("last30", "Last 30"),
        ("prior_period", "Prior period"),
        ("Lahore", "Lahore"),
        ("2026-10", "2026-10"),
        ("iPhone 15", "iPhone 15"),
    ],
)
def test_chart_labels_are_made_readable(raw: str, shown: str) -> None:
    from app.ai.agents.orchestrator import _readable

    assert _readable(raw) == shown
