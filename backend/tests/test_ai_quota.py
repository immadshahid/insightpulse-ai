"""Daily AI question allowance on Ask AI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.client import get_llm, set_llm_override
from tests.conftest import _register
from tests.fake_llm import FakeLLM, echo_answer, plan

API = "/api/v1"


@pytest.fixture
def limit_two(monkeypatch):
    monkeypatch.setattr(
        "app.core.ai_quota.get_settings", lambda: SimpleNamespace(ai_daily_questions=2)
    )


def ask(client, headers, dataset_id, llm):
    previous = get_llm()
    set_llm_override(llm)
    try:
        r = client.post(
            f"{API}/datasets/{dataset_id}/chat",
            headers=headers,
            json={"message": "What was total revenue?", "history": []},
        )
    finally:
        set_llm_override(previous)
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, headers, name, data):
    r = client.post(f"{API}/datasets", headers=headers, files={"file": (name, data, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset"]["id"]


def test_sales_questions_fall_back_to_rules_after_the_limit(client, raw_csv, limit_two) -> None:
    headers = _register(client, "quota-sales@example.com")
    ds = upload(client, headers, "s.csv", raw_csv)
    llm = FakeLLM({"chat_plan": plan(limit=5), "chat_answer": echo_answer})

    first, second, third = (ask(client, headers, ds, llm) for _ in range(3))
    assert first["source"] in ("llm", "template") and second["source"] in ("llm", "template")
    assert (first["ai_questions_left"], second["ai_questions_left"]) == (1, 0)
    assert third["source"] == "offline"  # the free rule-based answer
    assert "used today's 2 AI questions" in third["answer"]
    assert third["ai_questions_left"] == 0
    assert len([c for c in llm.calls if c["task"] == "chat_plan"]) == 2


def test_general_data_explains_the_limit(client, limit_two) -> None:
    headers = _register(client, "quota-general@example.com")
    csv = "name,score,passed\n" + "\n".join(f"p{i},{i % 50},{i % 2}" for i in range(60))
    ds = upload(client, headers, "g.csv", csv.encode())
    off = FakeLLM({})  # agents are never reached once the allowance is used up
    for _ in range(2):
        ask(client, headers, ds, off)
    body = ask(client, headers, ds, off)
    assert "used today's 2 AI questions" in body["answer"] and body["answerable"] is False


def test_limits_are_per_user(client, raw_csv, limit_two) -> None:
    a = _register(client, "quota-a@example.com")
    b = _register(client, "quota-b@example.com")
    llm = FakeLLM({"chat_plan": plan(limit=5), "chat_answer": echo_answer})
    ds_a, ds_b = upload(client, a, "a.csv", raw_csv), upload(client, b, "b.csv", raw_csv)
    for _ in range(3):
        ask(client, a, ds_a, llm)
    assert ask(client, b, ds_b, llm)["ai_questions_left"] == 1


def test_no_ai_means_nothing_is_counted(client, raw_csv, limit_two) -> None:
    headers = _register(client, "quota-off@example.com")
    ds = upload(client, headers, "o.csv", raw_csv)
    off = FakeLLM({})
    off.available = False
    for _ in range(3):
        body = ask(client, headers, ds, off)
    assert body["ai_questions_left"] == 2 and "used today" not in body["answer"]
