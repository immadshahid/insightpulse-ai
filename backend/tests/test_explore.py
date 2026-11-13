"""General data: EDA, Predict a column, kind switching, agents on any table, data report."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ai.agents.orchestrator import ask_agentic
from app.ai.agents.workspace import build_workspace
from app.ai.client import get_llm, set_llm_override
from app.eda.clean import clean_general
from app.eda.explore import explore, suggest_target
from app.eda.predict import PredictError, predict_column
from app.pipeline.profiler import profile_dataframe
from app.reports.data_pdf import render_data_pdf
from tests.fake_llm import FakeLLM
from tests.test_agents import (
    Script,
    ScriptedLLM,
    answer_json,
    kb_for,
    reply,
    report,
    tool,
)

API = "/api/v1"


def passengers(n: int = 600, seed: int = 3) -> pd.DataFrame:
    """A Titanic-like table: women and first class survive far more often."""
    rng = np.random.default_rng(seed)
    sex = rng.choice(["male", "female"], n, p=[0.64, 0.36])
    pclass = rng.choice([1, 2, 3], n, p=[0.24, 0.21, 0.55])
    age = rng.normal(30, 13, n).clip(1, 80).round()
    age[rng.random(n) < 0.2] = np.nan
    fare = np.where(pclass == 1, 85, np.where(pclass == 2, 21, 13)) * rng.lognormal(0, 0.4, n)
    p = 0.15 + 0.55 * (sex == "female") + 0.2 * (pclass == 1) - 0.05 * (pclass == 3)
    survived = (rng.random(n) < p.clip(0.02, 0.97)).astype(int)
    return pd.DataFrame(
        {
            "PassengerId": np.arange(1, n + 1),
            "Survived": survived,
            "Pclass": pclass,
            "Name": [f"Passenger {i}" for i in range(n)],
            "Sex": sex,
            "Age": age,
            "Fare": fare.round(2),
            "Embarked": rng.choice(["S", "C", "Q"], n, p=[0.72, 0.19, 0.09]),
        }
    )


@pytest.fixture(scope="module")
def titanic() -> pd.DataFrame:
    raw = passengers()
    df, _ = clean_general(raw, profile_dataframe(raw))
    return df


def test_cleaning_keeps_columns_and_drops_junk() -> None:
    raw = passengers(50)
    raw["Empty"] = None
    raw = pd.concat([raw, raw.iloc[:3]], ignore_index=True)
    df, report = clean_general(raw, profile_dataframe(raw))
    assert "Empty" not in df.columns and "Survived" in df.columns
    assert report["duplicate_rows"] == 3 and report["rows_out"] == 53
    assert pd.api.types.is_numeric_dtype(df["Fare"])


def test_explore_finds_the_outcome_and_the_gap(titanic) -> None:
    ex = explore(titanic)
    assert ex.target == "Survived" and "Survived" in ex.predictable
    assert ex.overview["rows"] == len(titanic)
    kinds = {c.name: c.kind for c in ex.columns}
    assert kinds["Survived"] == "yes/no" and kinds["Embarked"] == "category"
    assert kinds["Fare"] == "numeric" and kinds["PassengerId"] == "id"
    assert any("Sex" in i.headline for i in ex.insights if i.category == "target")
    assert any(c.title for c in ex.charts) and 0 <= ex.quality["score"] <= 100


def test_target_hint_needs_a_suitable_column() -> None:
    df = pd.DataFrame({"result": [f"r{i}" for i in range(100)], "x": range(100)})
    assert suggest_target(df, {"result": "text", "x": "numeric"}) is None


def test_prediction_beats_guessing_and_names_sex(titanic) -> None:
    p = predict_column(titanic, "Survived")
    assert p.task == "classification" and p.score > p.baseline
    assert p.features[0][0] in ("Sex", "Pclass", "Fare")
    assert "PassengerId" not in [f for f, _ in p.features]


def test_regression_target(titanic) -> None:
    p = predict_column(titanic, "Fare")
    assert p.task == "regression" and p.metric_name


@pytest.mark.parametrize("target", ["Name", "Nope"])
def test_unpredictable_columns_are_explained(titanic, target) -> None:
    with pytest.raises(PredictError):
        predict_column(titanic, target)


def test_data_report_pdf(titanic) -> None:
    ex = explore(titanic)
    pdf = render_data_pdf(
        ex,
        dataset_name="Titanic",
        filename="titanic.csv",
        prediction=predict_column(titanic, "Survived"),
    )
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page") >= 3


def test_agents_query_the_data_table(titanic) -> None:
    ws = build_workspace(titanic, titanic, {}, None, "general")
    assert ws.table == "data" and ws.date_min is None
    rows, _ = ws.sql.query('SELECT "Sex", AVG("Survived") AS rate FROM data GROUP BY 1')
    assert {r["Sex"] for r in rows} == {"male", "female"}
    female = next(r["rate"] for r in rows if r["Sex"] == "female")
    llm = Script(
        orchestrator=[
            reply(tool("ask_sql_agent", task="survival by sex")),
            answer_json(f"Women survived at a rate of {female}."),
        ],
        sql_agent=[
            reply(
                tool(
                    "run_sql",
                    query='SELECT "Sex", AVG("Survived") AS rate FROM data GROUP BY 1',
                    purpose="Survival by sex",
                )
            ),
            report(["E1"]),
        ],
    )
    answer, _ = ask_agentic(llm, ws, kb_for(ws), "Who survived more?")
    assert str(female) in answer.answer
    sent = llm.calls[0][1]
    assert "table `data`" in sent and "Data covers" not in sent


# ------------------------------------------------------------------ API


@pytest.fixture(scope="module")
def general(client, auth_headers) -> dict:
    csv = passengers().to_csv(index=False).encode()
    r = client.post(
        f"{API}/datasets",
        headers=auth_headers,
        files={"file": ("titanic.csv", csv, "text/csv")},
        data={"name": "Titanic"},
    )
    assert r.status_code == 201, r.text
    return r.json()["dataset"]


def test_upload_becomes_general_and_sales_routes_refuse(client, auth_headers, general) -> None:
    assert general["kind"] == "general" and general["status"] == "ready"
    ds = general["id"]
    r = client.get(f"{API}/datasets/{ds}/dashboard", headers=auth_headers)
    assert r.status_code == 409 and "general data" in r.json()["detail"]
    assert client.get(f"{API}/datasets/{ds}/insights", headers=auth_headers).status_code == 200


def test_explore_and_predict_endpoints(client, auth_headers, general) -> None:
    ds = general["id"]
    r = client.get(f"{API}/datasets/{ds}/explore", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "Survived" and body["charts"] and body["insights"]
    chart = client.get(body["charts"][0]["url"], headers=auth_headers)
    assert chart.status_code == 200

    focused = client.get(
        f"{API}/datasets/{ds}/explore", params={"target": "Pclass"}, headers=auth_headers
    )
    assert focused.json()["target"] == "Pclass"

    p = client.post(
        f"{API}/datasets/{ds}/predict", headers=auth_headers, json={"target": "Survived"}
    )
    assert p.status_code == 200, p.text
    assert p.json()["score"] > p.json()["baseline"] and p.json()["chart_url"]
    bad = client.post(f"{API}/datasets/{ds}/predict", headers=auth_headers, json={"target": "Name"})
    assert bad.status_code == 422


def test_data_report_endpoint(client, auth_headers, general) -> None:
    ds = general["id"]
    months = client.get(f"{API}/datasets/{ds}/report/months", headers=auth_headers).json()
    assert months == {"months": [], "default": ""}
    r = client.get(f"{API}/datasets/{ds}/report", headers=auth_headers)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert "data-report" in r.headers["content-disposition"]


def test_general_chat_without_ai_points_to_explore(client, auth_headers, general) -> None:
    previous = get_llm()
    off = FakeLLM({})
    off.available = False
    set_llm_override(off)
    try:
        r = client.post(
            f"{API}/datasets/{general['id']}/chat",
            headers=auth_headers,
            json={"message": "Who survived?", "history": []},
        )
    finally:
        set_llm_override(previous)
    assert r.status_code == 200 and "Explore" in r.json()["answer"]
    assert r.json()["answerable"] is False


def test_general_chat_uses_the_agents(client, auth_headers, general) -> None:
    script = Script(
        orchestrator=[
            reply(tool("search_knowledge", query="predict a column method")),
            answer_json("Predict trains a gradient-boosting model."),
        ]
    )
    previous = get_llm()
    set_llm_override(ScriptedLLM(FakeLLM({}), script))
    try:
        r = client.post(
            f"{API}/datasets/{general['id']}/chat",
            headers=auth_headers,
            json={"message": "How does predict work?", "history": []},
        )
    finally:
        set_llm_override(previous)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "agent" and r.json()["sources"]


def test_switching_kind(client, auth_headers, general, raw_csv) -> None:
    ds = general["id"]
    refused = client.put(f"{API}/datasets/{ds}/kind", headers=auth_headers, json={"kind": "sales"})
    assert refused.status_code == 422  # no date or revenue column to analyse as sales

    r = client.post(
        f"{API}/datasets", headers=auth_headers, files={"file": ("s.csv", raw_csv, "text/csv")}
    )
    sales = r.json()["dataset"]
    assert sales["kind"] == "sales"
    to_general = client.put(
        f"{API}/datasets/{sales['id']}/kind", headers=auth_headers, json={"kind": "general"}
    )
    assert to_general.status_code == 200 and to_general.json()["kind"] == "general"
    assert (
        client.get(f"{API}/datasets/{sales['id']}/explore", headers=auth_headers).status_code == 200
    )
    back = client.put(
        f"{API}/datasets/{sales['id']}/kind", headers=auth_headers, json={"kind": "sales"}
    )
    assert back.status_code == 200 and back.json()["kind"] == "sales"
    dash = client.get(f"{API}/datasets/{sales['id']}/dashboard", headers=auth_headers)
    assert dash.status_code == 200


def test_columns_that_restate_the_outcome_are_left_out(titanic) -> None:
    df = titanic.assign(alive=titanic["Survived"].map({1: "yes", 0: "no"}))
    ex = explore(df)
    assert ex.outcome_copies == ["alive"]
    assert not any(c.title.endswith(" by alive") for c in ex.charts)
    assert any(i.id == "outcome_copy:alive" for i in ex.insights)
    p = predict_column(df, "Survived")
    assert p.excluded == ["alive"] and "alive" not in [f for f, _ in p.features]
    assert p.score < 0.99
