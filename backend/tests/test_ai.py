"""AI layer with a mocked LLM: privacy, guardrails, mapping, narratives, chat, actions."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from app.ai.chat import ask
from app.ai.client import AnthropicLLM, DisabledLLM, LLMError, LLMUnavailableError
from app.ai.grounding import is_grounded, ungrounded_numbers
from app.ai.mapping import LLMColumnMapper, mapping_schema
from app.ai.narratives import write_narratives, write_summary
from app.ai.privacy import Pseudonymizer, mask_sample_rows, mask_text
from app.ai.query import DatasetSchema, QueryPlan, run_plan, validate_plan
from app.ai.recommendations import recommend, rule_based
from app.insights.engine import generate_insights
from app.pipeline.profiler import profile_dataframe, sample_rows
from tests.fake_llm import FakeLLM, echo_answer, echo_narratives, echo_summary, plan

LAST30 = {"type": "last_n_days", "n_days": 30, "month": None, "start": None, "end": None}


@pytest.fixture(scope="module")
def insights(clean_df, ctx):
    return generate_insights(clean_df, ctx)


# ------------------------------------------------------------------ privacy
def test_mask_text_removes_contact_details() -> None:
    out = mask_text("Ali 0347-8278233, +92 300 1234567, ali.k@example.pk, 35202-1234567-1")
    assert "0347" not in out and "1234567" not in out and "@" not in out
    assert out.count("[phone]") == 2 and "[email]" in out and "[id-number]" in out


def test_sample_rows_redact_personal_columns(raw_df) -> None:
    masked = mask_sample_rows(sample_rows(raw_df))
    assert len(masked) == 5
    for row in masked:
        assert row["Customer Name"] == "[redacted]" and row["Email"] == "[redacted]"
        assert row["Phone"] == "[redacted]" and row["City"] not in ("[redacted]",)


def test_pseudonymizer_round_trip() -> None:
    p = Pseudonymizer()
    text = p.mask_known("Compare C10023 with C10301", ["C10023", "C10301", "C1"])
    assert text == "Compare Customer 1 with Customer 2"
    assert p.restore("Customer 2 spent more than Customer 1") == "C10301 spent more than C10023"


# ------------------------------------------------------------------ grounding
@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Revenue was PKR 9.2M, down 2.9%, from 1,388 orders.", True),
        ("The top product has a 23% share.", True),  # 0.234 -> 23%
        ("Revenue was PKR 9.8M.", False),  # invented
        ("Orders fell 15%.", False),
        ("On 18 April 2026, 3 products led.", True),  # day, year, small count
    ],
)
def test_grounding(text: str, ok: bool) -> None:
    source = {"revenue": 9_203_112.5, "change_pct": -2.9, "share": 0.234, "orders": 1388}
    assert is_grounded(text, source) is ok


def test_ungrounded_lists_offending_numbers() -> None:
    assert ungrounded_numbers("Up 40% to 12.5K", {"a": 12500}) == ["40%"]


# ------------------------------------------------------------------ column mapping
def test_llm_mapper_sends_only_names_and_masked_rows(raw_df) -> None:
    columns = list(raw_df.columns)
    answer = {
        "mapping": {
            "date": "Order Date",
            "revenue": "Total",
            "quantity": "Qty",
            "product": "Category",
            "customer": "Customer ID",
            "region": "City",
            "order_id": "Order ID",
        },
        "confidence": dict.fromkeys(
            ["date", "revenue", "quantity", "product", "customer", "region", "order_id"], 0.9
        ),
    }
    llm = FakeLLM({"column_mapping": lambda _: answer})
    mapping = LLMColumnMapper(llm).map_columns(profile_dataframe(raw_df), sample_rows(raw_df))
    assert mapping.source == "llm" and mapping.product == "Category"
    sent = llm.sent_text()
    for col in ("Email", "Phone", "Customer Name"):
        for value in raw_df[col].head(5):
            assert str(value) not in sent
    assert sent.count("[redacted]") == 15  # 3 personal columns x 5 rows
    assert str(raw_df["Order ID"].iloc[5]) not in sent  # no 6th row
    enum = llm.calls[0]["schema"]["properties"]["mapping"]["properties"]["date"]["anyOf"][0]
    assert enum["enum"] == columns


@pytest.mark.parametrize(
    "bad",
    [
        {"mapping": {"date": "Total", "revenue": "Total"}, "confidence": {}},  # duplicate
        LLMError("down"),
    ],
)
def test_llm_mapper_falls_back_to_heuristics(raw_df, bad) -> None:
    llm = FakeLLM({"column_mapping": lambda _: bad})
    mapping = LLMColumnMapper(llm).map_columns(profile_dataframe(raw_df), sample_rows(raw_df))
    assert mapping.source == "heuristic" and mapping.revenue == "Total"


def test_mapping_schema_allows_null() -> None:
    choice = mapping_schema(["a", "b"])["properties"]["mapping"]["properties"]["region"]
    assert {"type": "null"} in choice["anyOf"]


# ------------------------------------------------------------------ narratives
def test_narratives_keep_only_grounded_text(insights) -> None:
    def handler(call):
        out = echo_narratives(call)
        out["items"][1]["narrative"] = "Sales jumped 87% thanks to 4,321 new buyers."
        return out

    llm = FakeLLM({"insight_narratives": handler})
    texts = write_narratives(llm, insights)
    assert insights[0].id in texts and insights[1].id not in texts
    assert len(texts) == len(insights) - 1


def test_summary_guardrail(insights) -> None:
    kpis = [
        {
            "key": "revenue",
            "label": "Revenue",
            "display": "PKR 9.2M",
            "value": 9.2e6,
            "change_pct": 4.1,
        }
    ]
    good = FakeLLM({"dashboard_summary": echo_summary})
    assert write_summary(good, "last 30 days", kpis, insights, "PKR").startswith("Revenue was")
    bad = FakeLLM({"dashboard_summary": lambda _: {"summary": "Revenue rose 55%."}})
    assert write_summary(bad, "last 30 days", kpis, insights, "PKR") is None
    assert write_summary(DisabledLLM(), "x", kpis, insights, "PKR") is None


# ------------------------------------------------------------------ chat
def test_chat_answer_uses_pandas_numbers(clean_df) -> None:
    llm = FakeLLM(
        {
            "chat_plan": plan(group_by="region", period=LAST30, compare="previous_period"),
            "chat_answer": echo_answer,
        }
    )
    out = ask(llm, clean_df, "Which city sold most in the last 30 days?", "PKR")
    assert out.source == "llm" and out.answerable and out.chart.kind == "bar_ranking"
    last = clean_df["date"].max().normalize()
    window = clean_df[clean_df["date"].dt.normalize() > last - pd.Timedelta(days=30)]
    expected = window.groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert out.result.rows[0].label == expected.index[0]
    assert out.result.rows[0].value == pytest.approx(expected.iloc[0])
    assert out.result.change_pct is not None and "compared with" in out.how
    assert len(out.follow_ups) == 3
    # The planner was given the data's last date and the real product/region values.
    assert str(last.date()) in llm.calls[0]["user"]


def test_chat_drops_invented_numbers(clean_df) -> None:
    llm = FakeLLM(
        {
            "chat_plan": plan(),
            "chat_answer": lambda _: {"answer": "Revenue was PKR 999M.", "follow_ups": []},
        }
    )
    out = ask(llm, clean_df, "Total revenue?", "PKR")
    assert out.source == "template" and "999" not in out.answer
    assert out.answer.startswith("Revenue for all data")


def test_chat_says_when_data_cannot_answer(clean_df) -> None:
    llm = FakeLLM(
        {
            "chat_plan": plan(
                answerable=False, reason="There is no cost column, so profit is unknown."
            )
        }
    )
    out = ask(llm, clean_df, "What was my profit?", "PKR")
    assert not out.answerable and out.answer.startswith("I can't answer that from this data")
    assert out.chart is None and out.follow_ups and len(llm.calls) == 1


def test_chat_rejects_unknown_values(clean_df) -> None:
    llm = FakeLLM(
        {"chat_plan": plan(filter=[{"field": "product", "op": "eq", "values": ["PlayStation"]}])}
    )
    out = ask(llm, clean_df, "How many PlayStations did I sell?", "PKR")
    assert not out.answerable and "couldn't find 'PlayStation'" in out.answer


def test_chat_pseudonymises_customers(clean_df) -> None:
    real = str(clean_df["customer"].value_counts().index[0])
    llm = FakeLLM(
        {
            "chat_plan": plan(filter=[{"field": "customer", "op": "eq", "values": ["Customer 1"]}]),
            "chat_answer": echo_answer,
        }
    )
    out = ask(llm, clean_df, f"How much has {real} spent?", "PKR")
    assert real not in llm.sent_text()
    assert "Customer 1" in llm.calls[0]["user"]
    assert out.result.total == pytest.approx(
        clean_df.loc[clean_df["customer"] == real, "revenue"].sum()
    )


def test_chat_group_by_customer_aliases_then_restores(clean_df) -> None:
    llm = FakeLLM({"chat_plan": plan(group_by="customer", limit=3), "chat_answer": echo_answer})
    out = ask(llm, clean_df, "Who are my top customers?", "PKR")
    top_real = out.result.rows[0].label
    assert top_real not in llm.sent_text()
    assert top_real in out.answer  # alias restored locally


def test_chat_planner_failure_raises(clean_df) -> None:
    with pytest.raises(LLMError):
        ask(FakeLLM({}), clean_df, "anything", "PKR")


def test_plan_execution_matches_pandas(clean_df) -> None:
    ds = DatasetSchema.from_frame(clean_df, "PKR")
    month = clean_df["month"].max()
    p = validate_plan(
        QueryPlan(
            metric="units",
            group_by="product",
            filter=[{"field": "region", "op": "eq", "values": ["karachi"]}],
            period={"type": "month", "month": month},
            limit=3,
        ),
        clean_df,
        ds,
    )
    res = run_plan(clean_df, p, ds)
    sub = clean_df[(clean_df["month"] == month) & (clean_df["region"] == "Karachi")]
    exp = sub.groupby("product")["quantity"].sum().sort_values(ascending=False).head(3)
    assert [r.label for r in res.rows] == list(exp.index)
    assert [r.value for r in res.rows] == pytest.approx(list(exp.values))
    assert p.filter[0].values == ["Karachi"]  # case-insensitive match


# ------------------------------------------------------------------ recommendations
def test_recommendations_llm_and_guardrail(insights) -> None:
    ids = [i.id for i in insights]

    def handler(_call):
        return {
            "actions": [
                {
                    "title": "Win back quiet customers",
                    "detail": "Send an offer.",
                    "impact": "high",
                    "based_on": [ids[0], "made-up-id"],
                },
                {
                    "title": "Boost sales 300%",
                    "detail": "Invented.",
                    "impact": "high",
                    "based_on": [],
                },
                {
                    "title": "Stock the top seller",
                    "detail": "Avoid stock-outs.",
                    "impact": "medium",
                    "based_on": [ids[1]],
                },
            ]
        }

    actions, source = recommend(FakeLLM({"recommendations": handler}), insights, "PKR")
    assert source == "llm" and [a.title for a in actions] == [
        "Win back quiet customers",
        "Stock the top seller",
    ]
    assert actions[0].based_on == [ids[0]]


def test_recommendations_fall_back_to_rules(insights) -> None:
    actions, source = recommend(DisabledLLM(), insights, "PKR")
    assert source == "rules" and 1 <= len(actions) <= 3
    assert actions == rule_based(insights, "PKR")
    failing, src = recommend(FakeLLM({}), insights, "PKR")
    assert src == "rules" and failing == actions


# ------------------------------------------------------------------ Anthropic client
def _fake_sdk(response):
    calls = []

    def create(**params):
        calls.append(params)
        return response

    messages = SimpleNamespace(create=create)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages)), calls


def _response(text: str, stop: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_anthropic_request_shape() -> None:
    client, calls = _fake_sdk(_response('{"ok": true}'))
    llm = AnthropicLLM("claude-opus-5-5", api_key="test", client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert llm.complete_json(task="t", system="s", user="u", schema=schema, effort="medium") == {
        "ok": True
    }
    p = calls[0]
    assert p["model"] == "claude-opus-5-5"
    assert p["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert p["messages"] == [{"role": "user", "content": "u"}] and p["system"] == "s"


def test_haiku_gets_no_server_fallback() -> None:
    llm = AnthropicLLM("claude-haiku-5-5", api_key="test", client=object())
    params = llm.request_params(system="s", user="u", schema={}, effort="low", max_tokens=10)
    assert "fallbacks" not in params and "betas" not in params


@pytest.mark.parametrize(
    ("text", "stop"), [("{}", "refusal"), ("not json", "end_turn"), ('{"a": 1', "max_tokens")]
)
def test_anthropic_bad_responses_raise(text: str, stop: str) -> None:
    client, _ = _fake_sdk(_response(text, stop))
    llm = AnthropicLLM("claude-opus-5-5", api_key="test", client=client)
    with pytest.raises(LLMError):
        llm.complete_json(task="t", system="s", user="u", schema={})


def test_disabled_llm() -> None:
    with pytest.raises(LLMUnavailableError):
        DisabledLLM().complete_json(task="t")


def test_haiku_requests_send_no_fallbacks() -> None:
    """Claude Haiku 5.5 has no server-side fallback; the parameter must not be sent."""
    llm = AnthropicLLM("claude-haiku-5-5", api_key="test", client=object())
    p = llm.request_params(
        system="s", user="u", schema={"type": "object"}, effort="low", max_tokens=10
    )
    assert p["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in p and "betas" not in p
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(p)
