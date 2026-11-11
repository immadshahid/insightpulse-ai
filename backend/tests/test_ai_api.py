"""AI endpoints with a mocked LLM (and without AI configured)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.client import LLMError, set_llm_override
from tests.fake_llm import FakeLLM, echo_answer, echo_narratives, echo_summary, plan

API = "/api/v1"
MAPPING = {
    "date": "Order Date",
    "revenue": "Total",
    "quantity": "Qty",
    "product": "Product",
    "customer": "Customer ID",
    "region": "City",
    "order_id": "Order ID",
}


def _fake() -> FakeLLM:
    return FakeLLM(
        {
            "column_mapping": lambda _: {
                "mapping": MAPPING,
                "confidence": dict.fromkeys(MAPPING, 0.95),
            },
            "insight_narratives": echo_narratives,
            "dashboard_summary": echo_summary,
            "chat_plan": plan(
                group_by="product",
                limit=5,
                period={
                    "type": "last_n_days",
                    "n_days": 30,
                    "month": None,
                    "start": None,
                    "end": None,
                },
            ),
            "chat_answer": echo_answer,
            "recommendations": lambda _: {
                "actions": [
                    {
                        "title": "Win back quiet customers",
                        "detail": "Send them an offer.",
                        "impact": "high",
                        "based_on": ["rfm_segments"],
                    }
                ]
            },
        }
    )


@pytest.fixture
def ai():
    fake = _fake()
    set_llm_override(fake)
    yield fake
    set_llm_override(None)


@pytest.fixture(scope="module")
def ai_dataset(client: TestClient, auth_headers, raw_csv) -> str:
    set_llm_override(_fake())
    try:
        r = client.post(
            f"{API}/datasets", headers=auth_headers, files={"file": ("ai.csv", raw_csv, "text/csv")}
        )
    finally:
        set_llm_override(None)
    assert r.status_code == 201, r.text
    assert r.json()["mapping"]["source"] == "llm"
    return r.json()["dataset"]["id"]


def test_chat_works_without_ai(client: TestClient, auth_headers, uploaded) -> None:
    r = client.post(
        f"{API}/datasets/{uploaded['dataset']['id']}/chat",
        json={"message": "Top products?"},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json()["source"] == "offline"
    assert r.json()["data"]["rows"] and r.json()["chart_url"]


def test_chat_endpoint(client: TestClient, auth_headers, ai_dataset, ai) -> None:
    r = client.post(
        f"{API}/datasets/{ai_dataset}/chat",
        headers=auth_headers,
        json={
            "message": "Which products sold most in the last 30 days?",
            "history": [{"role": "user", "content": "hi, I'm 0300-1234567"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "llm" and body["answerable"]
    assert len(body["data"]["rows"]) == 5 and body["how"].startswith("Summed revenue")
    assert body["follow_ups"] and body["plan"]["group_by"] == "product"
    png = client.get(body["chart_url"], headers=auth_headers)
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert "0300-1234567" not in ai.sent_text()  # history was masked


def test_chat_validation_and_planner_errors(
    client: TestClient, auth_headers, ai_dataset, ai
) -> None:
    assert (
        client.post(
            f"{API}/datasets/{ai_dataset}/chat", headers=auth_headers, json={"message": ""}
        ).status_code
        == 422
    )
    ai.handlers["chat_plan"] = lambda _: LLMError("boom")
    r = client.post(
        f"{API}/datasets/{ai_dataset}/chat", headers=auth_headers, json={"message": "Top products?"}
    )
    assert r.status_code == 200 and r.json()["source"] == "offline"


def test_recommendations_without_and_with_ai(
    client: TestClient, auth_headers, uploaded, ai_dataset
) -> None:
    rules = client.get(
        f"{API}/datasets/{uploaded['dataset']['id']}/recommendations", headers=auth_headers
    ).json()
    assert rules["source"] == "rules" and 1 <= len(rules["actions"]) <= 3
    set_llm_override(_fake())
    try:
        llm = client.get(
            f"{API}/datasets/{ai_dataset}/recommendations", headers=auth_headers
        ).json()
    finally:
        set_llm_override(None)
    assert llm["source"] == "llm" and llm["actions"][0]["based_on"] == ["rfm_segments"]


def test_insight_narratives_job(client: TestClient, auth_headers, ai_dataset, ai) -> None:
    first = client.get(f"{API}/datasets/{ai_dataset}/insights", headers=auth_headers).json()
    assert first["narratives"] in {"pending", "ready"}
    second = client.get(f"{API}/datasets/{ai_dataset}/insights", headers=auth_headers).json()
    assert second["narratives"] == "ready"
    assert all(i["narrative"] == i["headline"] + "." for i in second["items"])


def test_dashboard_ai_summary(client: TestClient, auth_headers, ai_dataset, ai) -> None:
    url = f"{API}/datasets/{ai_dataset}/dashboard"
    client.get(url, params={"period": "7d"}, headers=auth_headers)
    body = client.get(url, params={"period": "7d"}, headers=auth_headers).json()
    assert body["ai_summary"]["source"] == "llm" and body["ai_summary"]["status"] == "ready"
    assert body["ai_summary"]["text"].startswith("Revenue was")


def test_ai_off_status(client: TestClient, auth_headers, uploaded) -> None:
    ds = uploaded["dataset"]["id"]
    assert (
        client.get(f"{API}/datasets/{ds}/insights", headers=auth_headers).json()["narratives"]
        == "off"
    )
    summary = client.get(f"{API}/datasets/{ds}/dashboard", headers=auth_headers).json()[
        "ai_summary"
    ]
    assert summary == {**summary, "source": "template", "status": "off"}
