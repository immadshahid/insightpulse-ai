"""Natural-language data cleaning: fixed operations, suggestions, the AI planner, the API."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.ai.cleaning import describe_columns, plan_cleaning
from app.ai.client import LLMError, get_llm, set_llm_override
from app.core.cleaning import CleanError, apply_steps, parse_steps, suggestions
from tests.conftest import _register
from tests.fake_llm import FakeLLM

API = "/api/v1"


def people() -> pd.DataFrame:
    cities = ["Lahore", "lahore", "Karachi", "KARACHI ", "Lahore", "Multan", "Lahore", "Karachi"]
    df = pd.DataFrame(
        {
            "Name": [f"Person {i}" for i in range(40)],
            "Age": [20 + i if i % 5 else np.nan for i in range(40)],
            "City": [cities[i % 8] for i in range(40)],
            "Salary": [50_000 + 1_000 * i for i in range(39)] + [9_000_000],
            "Notes": [None] * 36 + ["a", "b", "c", "d"],
            "Email": [f"p{i}@example.com" for i in range(40)],
        }
    )
    return pd.concat([df, df.iloc[:3]], ignore_index=True)  # three exact duplicates


def run(steps: list[dict], df: pd.DataFrame | None = None):
    return apply_steps(people() if df is None else df, parse_steps(steps))


def step(op: str, **settings) -> dict:
    return {"op": op, **settings}


# ------------------------------------------------------------------ operations


def test_drop_missing_and_duplicates() -> None:
    out, preview = run([step("remove_duplicates"), step("drop_missing", columns=["age"])])
    assert preview.steps[0].rows_removed == 3 and preview.steps[1].rows_removed == 8
    assert len(out) == 32 and out["Age"].notna().all()
    assert preview.steps[1].description == "Remove rows where Age is missing"


@pytest.mark.parametrize("method", ["median", "zero", "value", "mean"])
def test_fill_missing_numbers(method: str) -> None:
    ages = people()["Age"]
    expected = {"median": ages.median(), "mean": ages.mean(), "zero": 0, "value": 99.0}[method]
    out, preview = run([step("fill_missing", column="Age", method=method, value="99")])
    assert out["Age"].isna().sum() == 0 and out.loc[0, "Age"] == pytest.approx(expected, abs=1e-3)
    assert preview.steps[0].cells_changed == 9


def test_fill_missing_text_and_bad_requests() -> None:
    out, _ = run([step("fill_missing", column="Notes", method="value", value="none")])
    assert (out["Notes"] == "none").sum() == 39
    with pytest.raises(CleanError, match="has no numbers"):
        run([step("fill_missing", column="City", method="median")])
    with pytest.raises(CleanError, match="doesn't fit"):
        run([step("fill_missing", column="Age", method="value", value="unknown")])


def test_replace_values_merges_spellings_ignoring_case_and_spaces() -> None:
    out, preview = run(
        [step("replace_values", column="city", values=["lahore", "LHR"], value="Lahore")]
    )
    assert set(out["City"]) == {"Lahore", "Karachi", "KARACHI ", "Multan"}
    assert preview.steps[0].cells_changed == 6


def test_filter_rows_keep_and_remove() -> None:
    kept, _ = run([step("filter_rows", column="Age", comparison="gte", value="40", keep=True)])
    assert kept["Age"].min() >= 40
    removed, preview = run(
        [step("filter_rows", column="City", comparison="eq", value="multan", keep=False)]
    )
    assert "Multan" not in set(removed["City"])
    assert preview.steps[0].description == "Remove rows where City is multan"
    text, _ = run([step("filter_rows", column="Name", comparison="contains", value="son 1")])
    assert not text["Name"].str.contains("son 1").any()
    with pytest.raises(CleanError, match="isn't a number"):
        run([step("filter_rows", column="Age", comparison="gt", value="old")])


def test_columns_case_spaces_outliers_and_types() -> None:
    out, preview = run(
        [
            step("drop_columns", columns=["notes"]),
            step("rename_column", column="Salary", new_name="Monthly pay"),
            step("trim_text", columns=["City"]),
            step("change_case", column="City", case="title"),
            step("remove_outliers", column="Monthly pay"),
            step("convert_type", column="Age", to="text"),
        ]
    )
    assert "Notes" not in out.columns and "Monthly pay" in out.columns
    assert set(out["City"]) == {"Lahore", "Karachi", "Multan"}
    assert out["Monthly pay"].max() < 1_000_000
    assert preview.columns_after == 5 and preview.steps[4].rows_removed == 1
    assert out["Age"].dropna().map(type).eq(str).all()


def test_plans_that_make_no_sense_are_refused() -> None:
    with pytest.raises(CleanError, match="no column called 'Wage'"):
        run([step("drop_missing", columns=["Wage"])])
    with pytest.raises(CleanError, match="every row"):
        run([step("filter_rows", column="Age", comparison="gt", value="500", keep=True)])
    with pytest.raises(CleanError, match="every column"):
        run([step("drop_columns", columns=list(people().columns))])
    with pytest.raises(CleanError, match="already a column"):
        run([step("rename_column", column="Age", new_name="city")])
    with pytest.raises(CleanError, match="not a cleaning step"):
        run([step("run_python", value="import os")])
    with pytest.raises(CleanError, match="up to 12"):
        run([step("remove_duplicates")] * 13)


def test_the_original_table_is_not_changed() -> None:
    df = people()
    before = df.copy()
    run([step("fill_missing", column="Age", method="zero"), step("trim_text")], df)
    pd.testing.assert_frame_equal(df, before)


def test_suggestions_find_the_obvious_problems() -> None:
    found = {s["label"]: s["steps"] for s in suggestions(people())}
    assert "Remove 3 duplicate rows" in found
    assert any(label.startswith("Remove Notes (9") for label in found)
    assert any(label.startswith("Fill 9 empty cells in Age with the median") for label in found)
    spelling = next(steps for label, steps in found.items() if "inconsistent spelling" in label)
    out, _ = run([*spelling, step("trim_text", columns=["City"])])
    assert set(out["City"]) == {"Lahore", "Karachi", "Multan"}
    for steps in found.values():
        run(steps)  # every suggestion is a plan that runs


# ------------------------------------------------------------------ AI planner


def plan(*steps: dict, problem: str | None = None):
    blank = {
        "column": None,
        "columns": [],
        "method": None,
        "value": None,
        "new_name": None,
        "values": [],
        "comparison": None,
        "keep": None,
        "case": None,
        "to": None,
    }
    return lambda call: {"steps": [{**blank, **s} for s in steps], "problem": problem}


def test_the_model_sees_examples_but_no_personal_values() -> None:
    llm = FakeLLM({"clean_plan": plan(step("drop_missing", columns=["Age"]))})
    steps, note = plan_cleaning(llm, people(), "drop rows without age, mail me at me@example.com")
    assert note is None
    assert steps[0]["op"] == "drop_missing"
    sent = llm.sent_text()
    assert "lahore" in sent and "Person 1" not in sent and "p1@example.com" not in sent
    assert "me@example.com" not in sent and "[email]" in sent
    columns = {c["name"]: c for c in describe_columns(people())}
    assert columns["Email"]["examples"] == "[personal data, not shown]"
    assert columns["Age"]["empty_cells"] == 9 and "examples" not in columns["Age"]


def test_requests_outside_cleaning_are_explained() -> None:
    llm = FakeLLM({"clean_plan": plan(problem="I can't add calculated columns yet.")})
    with pytest.raises(CleanError, match="calculated columns"):
        plan_cleaning(llm, people(), "add a profit column")


# ------------------------------------------------------------------ API


@pytest.fixture(scope="module")
def user(client) -> dict[str, str]:
    return _register(client, "cleaner@example.com")


@pytest.fixture(scope="module")
def dataset_id(client, user) -> str:
    r = client.post(
        f"{API}/datasets",
        headers=user,
        files={"file": ("people.csv", people().to_csv(index=False).encode(), "text/csv")},
        data={"name": "People"},
    )
    assert r.status_code == 201, r.text
    return r.json()["dataset"]["id"]


def with_llm(llm, call):
    previous = get_llm()
    set_llm_override(llm)
    try:
        return call()
    finally:
        set_llm_override(previous)


def test_suggestions_preview_and_apply(client, user, dataset_id) -> None:
    base = f"{API}/datasets/{dataset_id}/clean"
    s = client.get(f"{base}/suggestions", headers=user)
    assert s.status_code == 200, s.text
    steps = next(
        x["steps"] for x in s.json()["suggestions"] if x["label"].startswith("Remove 3 dup")
    )
    steps.append(step("drop_columns", columns=["Notes"]))

    p = client.post(f"{base}/preview", headers=user, json={"steps": steps})
    assert p.status_code == 200, p.text
    assert (p.json()["rows_before"], p.json()["rows_after"]) == (43, 40)
    assert p.json()["steps"][1]["effect"] == "Removes 1 column"

    a = client.post(f"{base}/apply", headers=user, json={"steps": steps})
    assert a.status_code == 201, a.text
    made = a.json()["dataset"]
    assert made["name"] == "People (cleaned)" and made["row_count"] == 40
    assert made["id"] != dataset_id
    original = client.get(f"{API}/datasets/{dataset_id}/profile", headers=user).json()
    assert original["dataset"]["row_count"] == 43  # untouched

    bad = client.post(
        f"{base}/preview", headers=user, json={"steps": [step("drop_missing", columns=["Wage"])]}
    )
    assert bad.status_code == 422 and "no column called 'Wage'" in bad.json()["detail"]


def test_typed_request_becomes_checked_steps(client, user, dataset_id) -> None:
    url = f"{API}/datasets/{dataset_id}/clean/plan"
    body = {"instruction": "Remove rows where age is missing and call Salary 'Pay'"}
    llm = FakeLLM(
        {
            "clean_plan": plan(
                step("drop_missing", columns=["age"]),
                step("rename_column", column="salary", new_name="Pay"),
                problem="There is no Notes column, so I left that out.",
            )
        }
    )
    r = with_llm(llm, lambda: client.post(url, headers=user, json=body))
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "There is no Notes column, so I left that out."
    steps = r.json()["steps"]
    assert steps[0]["columns"] == ["Age"] and steps[1]["column"] == "Salary"  # real names

    wrong = FakeLLM({"clean_plan": plan(step("drop_missing", columns=["Wage"]))})
    r = with_llm(wrong, lambda: client.post(url, headers=user, json=body))
    assert r.status_code == 422 and "Wage" in r.json()["detail"]

    partly = FakeLLM(
        {"clean_plan": plan(step("drop_columns", columns=["Remarks"]), step("remove_duplicates"))}
    )
    r = with_llm(partly, lambda: client.post(url, headers=user, json=body))
    assert r.status_code == 200, r.text  # the part that works is kept
    assert [s["op"] for s in r.json()["steps"]] == ["remove_duplicates"]
    assert r.json()["note"].startswith("Skipped: There is no column called 'Remarks'")

    broken = FakeLLM({"clean_plan": lambda call: LLMError("down")})
    r = with_llm(broken, lambda: client.post(url, headers=user, json=body))
    assert r.status_code == 503 and "try again" in r.json()["detail"]

    off = FakeLLM({})
    off.available = False
    r = with_llm(off, lambda: client.post(url, headers=user, json=body))
    assert r.status_code == 503 and "suggested fixes still work" in r.json()["detail"]


def test_typed_requests_count_towards_the_daily_limit(client, dataset_id, user, monkeypatch):
    monkeypatch.setattr(
        "app.core.ai_quota.get_settings", lambda: SimpleNamespace(ai_daily_questions=0)
    )
    url = f"{API}/datasets/{dataset_id}/clean/plan"
    llm = FakeLLM({"clean_plan": plan(step("remove_duplicates"))})
    ok = with_llm(llm, lambda: client.post(url, headers=user, json={"instruction": "dedupe"}))
    assert ok.status_code == 200 and ok.json()["ai_questions_left"] is None  # 0 = no limit

    fresh = _register(client, "cleaner-limited@example.com")
    r = client.post(
        f"{API}/datasets",
        headers=fresh,
        files={"file": ("p.csv", people().to_csv(index=False).encode(), "text/csv")},
    )
    limited = f"{API}/datasets/{r.json()['dataset']['id']}/clean/plan"
    monkeypatch.setattr(
        "app.core.ai_quota.get_settings", lambda: SimpleNamespace(ai_daily_questions=1)
    )
    first = with_llm(llm, lambda: client.post(limited, headers=fresh, json={"instruction": "x1"}))
    second = with_llm(llm, lambda: client.post(limited, headers=fresh, json={"instruction": "x2"}))
    assert first.status_code == 200 and first.json()["ai_questions_left"] == 0
    assert second.status_code == 429 and "used today's 1 AI questions" in second.json()["detail"]


def test_other_users_cannot_clean_your_data(client, other_headers, dataset_id) -> None:
    r = client.get(f"{API}/datasets/{dataset_id}/clean/suggestions", headers=other_headers)
    assert r.status_code == 404
