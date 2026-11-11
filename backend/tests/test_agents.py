"""Agentic RAG with a scripted Claude: sandboxes, retrieval, loops, grounding, fallback."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.ai.agents.knowledge import KnowledgeBase, build_passages
from app.ai.agents.loop import AgentError, Tool, run_agent
from app.ai.agents.orchestrator import ask_agentic
from app.ai.agents.specialists import csv_tools, run_sql_agent, sql_tools
from app.ai.agents.workspace import Ledger, ToolInputError, build_workspace
from app.ai.client import AnthropicLLM, get_llm, set_llm_override
from tests.fake_llm import FakeLLM, echo_answer, plan

API = "/api/v1"
SCHEMA = {"type": "object"}


def tool(name, **args):
    return SimpleNamespace(
        type="tool_use", id=f"id_{name}_{time.perf_counter_ns()}", name=name, input=args
    )


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage={})


def final(data):
    return reply(SimpleNamespace(type="text", text=json.dumps(data)), stop="end_turn")


def report(ids):
    return final({"findings": "done", "evidence_ids": ids, "answered": True})


def answer_json(text, chart=None):
    return final({"answer": text, "follow_ups": ["Next?"], "answerable": True, "chart": chart})


class Script:
    """Plays a fixed list of responses per agent and records what each was sent."""

    def __init__(self, **scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls = []

    def agent_turn(self, *, task, messages, tools_enabled=True, **_):
        self.calls.append((task, json.dumps(messages, default=str), tools_enabled))
        return self.scripts[task].pop(0)


def loop(llm, tools=(), max_turns=4, deadline=None):
    return run_agent(
        llm,
        name="a",
        system="s",
        user="u",
        tools=list(tools),
        schema=SCHEMA,
        effort="low",
        max_turns=max_turns,
        deadline=time.monotonic() + 30 if deadline is None else deadline,
    )


@pytest.fixture(scope="module")
def ws(clean_df, raw_df, pipeline_result):
    return build_workspace(clean_df, raw_df, pipeline_result.mapping.model_dump(), "PKR")


def kb_for(ws, insights=(), forecasts=()):
    return KnowledgeBase(
        build_passages(list(insights), {}, list(forecasts), ws.pseudo, ws.real_customers)
    )


# ----------------------------------------------------------------- sandboxes
def test_no_personal_data_in_either_copy(ws, pipeline_result) -> None:
    assert not {"Email", "Phone", "Customer Name"} & set(ws.csv.columns)
    customer_col = pipeline_result.mapping.model_dump()["customer"]
    assert ws.csv[customer_col].dropna().str.startswith("Customer ").all()
    rows, _ = ws.sql.query("SELECT customer, SUM(revenue) r FROM sales GROUP BY 1 LIMIT 3")
    assert all(r["customer"].startswith("Customer ") for r in rows)


def test_sql_matches_pandas(ws, clean_df) -> None:
    rows, truncated = ws.sql.query("SELECT SUM(revenue) AS total FROM sales")
    assert not truncated and rows[0]["total"] == pytest.approx(clean_df["revenue"].sum(), abs=0.01)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "DELETE FROM sales",
        "INSERT INTO sales(revenue) VALUES (1)",
        "SELECT 1; DROP TABLE sales",
        "ATTACH DATABASE 'x.db' AS x",
        "PRAGMA table_info(sales)",
        "WITH t AS (SELECT 1) DELETE FROM sales",
        "SELECT load_extension('x')",
        "SELECT * FROM users",
    ],
)
def test_sql_rejects_anything_but_reads_of_sales(ws, sql) -> None:
    with pytest.raises(ToolInputError):
        ws.sql.query(sql)
    assert ws.sql.query("SELECT COUNT(*) c FROM sales")[0][0]["c"] > 0


def test_runaway_sql_is_stopped(ws) -> None:
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT MAX(x) FROM n"
    started = time.monotonic()
    with pytest.raises(ToolInputError):
        ws.sql.query(sql)
    assert time.monotonic() - started < 8


def test_rows_are_capped(ws) -> None:
    rows, truncated = ws.sql.query("SELECT * FROM sales")
    assert len(rows) == 200 and truncated


def csv_tool(ws, name, ledger=None):
    return next(t for t in csv_tools(ws, ledger or Ledger()) if t.name == name)


def test_csv_agent_reaches_unmapped_columns(ws, raw_df) -> None:
    schema = csv_tool(ws, "csv_schema").run({})
    assert "Category" in [c["name"] for c in schema["columns"]]
    out = csv_tool(ws, "csv_query").run(
        {
            "purpose": "lines per category",
            "filters": [],
            "group_by": ["Category"],
            "aggregations": [{"column": "Category", "func": "count"}],
            "sort_by": "count_Category",
            "descending": True,
            "limit": 5,
        }
    )
    assert out["evidence_id"] == "E1"
    assert out["rows"][0]["count_Category"] == raw_df["Category"].value_counts().iloc[0]


def test_csv_tool_errors_explain_themselves(ws) -> None:
    with pytest.raises(ToolInputError, match="No column"):
        csv_tool(ws, "csv_describe").run({"column": "Nope"})


def test_tools_are_strict_and_none_runs_code(ws) -> None:
    tools = csv_tools(ws, Ledger()) + sql_tools(ws, Ledger())
    assert all(t.definition()["strict"] is True for t in tools)
    assert {t.name for t in tools} == {
        "csv_schema",
        "csv_query",
        "csv_describe",
        "csv_correlate",
        "sql_schema",
        "run_sql",
    }


# ----------------------------------------------------------------- retrieval
def test_retrieval_finds_the_right_passage(ws) -> None:
    top = kb_for(ws).search("how is average order value calculated", k=1)[0][0]
    assert top.title == "Definition: average order value"


def test_retrieval_returns_nothing_for_nonsense(ws) -> None:
    assert kb_for(ws).search("zzzz qqqq") == []


def test_knowledge_masks_customers(ws) -> None:
    real = ws.real_customers[0]
    insight = SimpleNamespace(
        category="customers",
        tag="Top",
        headline=f"{real} spends most",
        why_it_matters="x",
        narrative=None,
        data={},
    )
    assert all(real not in p.text for p in kb_for(ws, [insight]).passages)


# ----------------------------------------------------------------- loop
def test_loop_runs_tools_then_returns() -> None:
    llm = Script(a=[reply(tool("echo", x="1")), final({"ok": True})])
    out = loop(llm, [Tool("echo", "d", {"x": {"type": "string"}}, lambda a: {"got": a["x"]})])
    assert out == {"ok": True} and "got" in llm.calls[1][1]


def test_tool_errors_go_back_to_the_model() -> None:
    def boom(_):
        raise ToolInputError("bad column")

    llm = Script(a=[reply(tool("b")), final({"ok": 1})])
    loop(llm, [Tool("b", "d", {}, boom)])
    assert "bad column" in llm.calls[1][1] and "is_error" in llm.calls[1][1]


def test_last_turn_disables_tools() -> None:
    llm = Script(a=[reply(tool("t")), final({"ok": 1})])
    loop(llm, [Tool("t", "d", {}, lambda _: 1)], max_turns=2)
    assert [c[2] for c in llm.calls] == [True, False]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reasons_raise(stop) -> None:
    with pytest.raises(AgentError):
        loop(Script(a=[reply(stop=stop)]))


def test_deadline_stops_the_loop() -> None:
    with pytest.raises(AgentError, match="time"):
        loop(Script(a=[]), deadline=time.monotonic())


# ----------------------------------------------------------------- team
def test_sql_agent_collects_evidence(ws) -> None:
    llm = Script(
        sql_agent=[
            reply(tool("run_sql", query="SELECT COUNT(*) AS n FROM sales", purpose="Count")),
            report(["E1"]),
        ]
    )
    ledger = Ledger()
    out = run_sql_agent(llm, ws, ledger, "count", time.monotonic() + 30)
    assert list(out["evidence"]) == ["E1"] and "COUNT" in ledger.steps[0]["detail"]


def team(*orchestrator_tail):
    return Script(
        orchestrator=[reply(tool("ask_sql_agent", task="total")), *orchestrator_tail],
        sql_agent=[
            reply(tool("run_sql", query="SELECT SUM(revenue) AS total FROM sales", purpose="T")),
            report(["E1"]),
        ],
    )


def test_team_answers_with_grounded_numbers(ws, clean_df) -> None:
    total = round(float(clean_df["revenue"].sum()), 2)
    answer, ledger = ask_agentic(
        team(answer_json(f"Revenue was {total:,.2f}.")), ws, kb_for(ws), "Total revenue?"
    )
    assert answer.source == "agent" and f"{total:,.2f}" in answer.answer
    assert "SQL agent" in answer.how and ledger.steps


def test_invented_number_gets_one_repair(ws, clean_df) -> None:
    total = round(float(clean_df["revenue"].sum()), 2)
    llm = team(answer_json("Revenue was 123,456,789."), answer_json(f"It was {total:,.2f}."))
    answer, _ = ask_agentic(llm, ws, kb_for(ws), "Total?")
    assert "123,456,789" not in answer.answer
    assert "not in any tool result" in llm.calls[-1][1]


def test_repeatedly_invented_number_fails(ws) -> None:
    llm = team(answer_json("Revenue was 123,456,789."), answer_json("Still 987,654,321."))
    with pytest.raises(AgentError):
        ask_agentic(llm, ws, kb_for(ws), "Total?")


def test_real_customer_never_reaches_the_model_and_is_restored(ws) -> None:
    real, alias = next(iter(ws.pseudo.forward.items()))
    llm = Script(orchestrator=[answer_json(f"{alias} is your best buyer.")])
    answer, _ = ask_agentic(llm, ws, kb_for(ws), f"How is {real} doing?")
    assert real not in llm.calls[0][1] and alias in llm.calls[0][1]
    assert real in answer.answer


def test_retrieved_numbers_count_as_evidence(ws) -> None:
    kb = kb_for(ws, forecasts=[{"target": "revenue", "horizon_days": 90, "total": 38100000.0}])
    llm = Script(
        orchestrator=[
            reply(tool("search_knowledge", query="revenue forecast expected total")),
            answer_json("Expected revenue is 38.1M."),
        ]
    )
    answer, ledger = ask_agentic(llm, ws, kb, "Forecast?")
    assert "38.1M" in answer.answer and ledger.sources


def test_chart_comes_from_real_rows(ws) -> None:
    sql = "SELECT region, SUM(revenue) AS r FROM sales GROUP BY 1 ORDER BY 2 DESC"
    chart = {
        "evidence_id": "E1",
        "kind": "bar",
        "label_column": "region",
        "value_column": "r",
        "is_money": True,
    }
    llm = Script(
        orchestrator=[reply(tool("ask_sql_agent", task="x")), answer_json("See chart.", chart)],
        sql_agent=[reply(tool("run_sql", query=sql, purpose="By city")), report(["E1"])],
    )
    answer, _ = ask_agentic(llm, ws, kb_for(ws), "By city?")
    assert answer.chart.kind == "bar_ranking" and len(answer.chart.payload["labels"]) >= 2


# ----------------------------------------------------------------- client and API
def test_request_uses_tools_and_caching() -> None:
    created = {}
    resp = SimpleNamespace(stop_reason="end_turn", content=[], usage={})
    raw = SimpleNamespace(
        beta=SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kw: created.update(kw) or resp)
        )
    )
    raw.with_options = lambda **_: raw
    AnthropicLLM("claude-opus-5-5", client=raw).agent_turn(
        task="t",
        system="s",
        messages=[{"role": "user", "content": "q"}],
        tools=[{"name": "x"}],
        schema=SCHEMA,
        effort="low",
        tools_enabled=False,
    )
    assert created["tool_choice"] == {"type": "none"}
    assert created["cache_control"] == {"type": "ephemeral"}
    assert created["messages"] == [{"role": "user", "content": "q"}]


class ScriptedLLM(FakeLLM):
    def __init__(self, base, script):
        self.__dict__.update(base.__dict__)
        self._script = script

    def agent_turn(self, **kw):
        return self._script.agent_turn(**kw)


def post_chat(client, auth_headers, uploaded, llm):
    previous = get_llm()
    set_llm_override(llm)
    try:
        return client.post(
            f"{API}/datasets/{uploaded['dataset']['id']}/chat",
            headers=auth_headers,
            json={"message": "What is AOV?", "history": []},
        )
    finally:
        set_llm_override(previous)


def test_chat_api_returns_steps_and_sources(client, auth_headers, uploaded) -> None:
    script = Script(
        orchestrator=[
            reply(tool("search_knowledge", query="average order value definition")),
            answer_json("Average order value is revenue divided by orders."),
        ]
    )
    r = post_chat(client, auth_headers, uploaded, ScriptedLLM(FakeLLM({}), script))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "agent" and body["steps"][0]["agent"] == "knowledge"
    assert body["sources"]


def test_chat_api_falls_back_when_agents_fail(client, auth_headers, uploaded) -> None:
    base = FakeLLM({"chat_plan": plan(limit=5), "chat_answer": echo_answer})
    llm = ScriptedLLM(base, Script(orchestrator=[reply(stop="refusal")]))
    r = post_chat(client, auth_headers, uploaded, llm)
    assert r.status_code == 200, r.text
    assert r.json()["source"] in ("llm", "template") and r.json()["steps"] == []
