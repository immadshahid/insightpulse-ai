"""API: auth, upload, profile, mapping, dashboard, insights, charts, ownership."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_root_redirects_to_docs(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/docs"


def test_register_login_flow(client: TestClient) -> None:
    body = {"email": "Flow@Example.com", "password": "another-pass"}
    assert client.post(f"{API}/auth/register", json=body).status_code == 201
    assert client.post(f"{API}/auth/register", json=body).status_code == 409
    r = client.post(
        f"{API}/auth/login", json={"email": "flow@example.com", "password": "another-pass"}
    )
    assert r.status_code == 200 and r.json()["user"]["email"] == "flow@example.com"
    bad = client.post(
        f"{API}/auth/login", json={"email": "flow@example.com", "password": "wrong-pass"}
    )
    assert bad.status_code == 401


def test_register_validates_input(client: TestClient) -> None:
    assert (
        client.post(
            f"{API}/auth/register", json={"email": "not-an-email", "password": "longenough"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/auth/register", json={"email": "a@example.com", "password": "short"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/datasets"),
        ("post", "/datasets"),
        ("get", "/datasets/x/profile"),
        ("put", "/datasets/x/mapping"),
        ("get", "/datasets/x/dashboard"),
        ("get", "/datasets/x/insights"),
        ("get", "/charts/x.png"),
    ],
)
def test_routes_require_jwt(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(f"{API}{path}").status_code == 401
    bad = {"Authorization": "Bearer not.a.token"}
    assert getattr(client, method)(f"{API}{path}", headers=bad).status_code == 401


def test_upload_returns_profile_mapping_quality(uploaded: dict) -> None:
    assert uploaded["dataset"]["status"] == "ready"
    assert uploaded["dataset"]["name"] == "My shop"
    assert uploaded["dataset"]["currency"] == "PKR"
    assert uploaded["mapping"]["date"] == "Order Date"
    assert uploaded["mapping"]["revenue"] == "Total"
    assert uploaded["mapping"]["customer"] == "Customer ID"
    assert 0 <= uploaded["quality"]["score"] <= 100
    assert uploaded["required_roles"] == ["date", "revenue"]
    assert len(uploaded["profile"]["columns"]) == 13


def test_list_and_profile(client: TestClient, auth_headers, uploaded) -> None:
    ds_id = uploaded["dataset"]["id"]
    listed = client.get(f"{API}/datasets", headers=auth_headers).json()
    assert ds_id in [d["id"] for d in listed]
    prof = client.get(f"{API}/datasets/{ds_id}/profile", headers=auth_headers)
    assert prof.status_code == 200 and prof.json()["dataset"]["id"] == ds_id


@pytest.mark.parametrize("period", ["7d", "30d", "90d", "1y"])
def test_dashboard(client: TestClient, auth_headers, uploaded, period: str) -> None:
    ds_id = uploaded["dataset"]["id"]
    r = client.get(
        f"{API}/datasets/{ds_id}/dashboard", params={"period": period}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [k["key"] for k in body["kpis"]] == [
        "revenue",
        "orders",
        "avg_order_value",
        "active_customers",
    ]
    # The test data covers 8 months: 1y has no previous year to compare against.
    if period == "1y":
        assert all(k["change_pct"] is None and k["direction"] is None for k in body["kpis"])
    else:
        assert all(k["change_pct"] is not None for k in body["kpis"])
    assert body["ai_summary"]["text"].startswith("Revenue was")
    assert all(len(k["spark"]) >= 7 for k in body["kpis"])
    assert 1 <= len(body["top_insights"]) <= 3
    assert body["charts"]["revenue_trend"].startswith(f"{API}/charts/")


def test_dashboard_rejects_bad_period(client: TestClient, auth_headers, uploaded) -> None:
    ds_id = uploaded["dataset"]["id"]
    r = client.get(
        f"{API}/datasets/{ds_id}/dashboard", params={"period": "2w"}, headers=auth_headers
    )
    assert r.status_code == 422


def test_insights_feed_and_filter(client: TestClient, auth_headers, uploaded) -> None:
    ds_id = uploaded["dataset"]["id"]
    items = client.get(f"{API}/datasets/{ds_id}/insights", headers=auth_headers).json()["items"]
    assert 5 <= len(items) <= 10
    assert any(i["category"] == "anomalies" for i in items)
    anomalies = client.get(
        f"{API}/datasets/{ds_id}/insights", params={"category": "anomalies"}, headers=auth_headers
    ).json()["items"]
    assert anomalies and all(i["category"] == "anomalies" for i in anomalies)


def test_chart_png_themes_and_etag(client: TestClient, auth_headers, uploaded) -> None:
    ds_id = uploaded["dataset"]["id"]
    items = client.get(f"{API}/datasets/{ds_id}/insights", headers=auth_headers).json()["items"]
    url = next(i["chart_url"] for i in items if i["chart_url"])
    light = client.get(url, headers=auth_headers)
    dark = client.get(url, params={"theme": "dark"}, headers=auth_headers)
    assert light.status_code == dark.status_code == 200
    assert light.headers["content-type"] == "image/png"
    assert light.content[:4] == b"\x89PNG" and light.content != dark.content
    cached = client.get(url, headers={**auth_headers, "If-None-Match": light.headers["etag"]})
    assert cached.status_code == 304


def test_other_user_cannot_see_dataset_or_chart(
    client: TestClient, auth_headers, other_headers, uploaded
) -> None:
    ds_id = uploaded["dataset"]["id"]
    for path in ("profile", "dashboard", "insights"):
        assert (
            client.get(f"{API}/datasets/{ds_id}/{path}", headers=other_headers).status_code == 404
        )
    items = client.get(f"{API}/datasets/{ds_id}/insights", headers=auth_headers).json()["items"]
    url = next(i["chart_url"] for i in items if i["chart_url"])
    assert client.get(url, headers=other_headers).status_code == 404
    assert client.get(f"{API}/datasets", headers=other_headers).json() == []


def test_upload_rejects_unsupported_file(client: TestClient, auth_headers) -> None:
    r = client.post(
        f"{API}/datasets",
        headers=auth_headers,
        files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400


def test_needs_mapping_then_user_mapping(client: TestClient, auth_headers, raw_df) -> None:
    # Rename columns so the heuristics cannot find date/revenue.
    df = raw_df.rename(columns={"Order Date": "When", "Total": "Paid"})
    r = client.post(
        f"{API}/datasets",
        headers=auth_headers,
        files={"file": ("odd.csv", df.to_csv(index=False).encode(), "text/csv")},
    )
    assert r.status_code == 201
    body = r.json()
    ds_id = body["dataset"]["id"]
    assert body["dataset"]["status"] == "needs_mapping"
    assert client.get(f"{API}/datasets/{ds_id}/dashboard", headers=auth_headers).status_code == 409

    bad = client.put(
        f"{API}/datasets/{ds_id}/mapping",
        headers=auth_headers,
        json={"date": "When", "revenue": "When"},
    )
    assert bad.status_code == 422

    mapping = {
        **{
            k: v
            for k, v in body["mapping"].items()
            if k in ("quantity", "product", "customer", "region", "order_id")
        },
        "date": "When",
        "revenue": "Paid",
    }
    ok = client.put(f"{API}/datasets/{ds_id}/mapping", headers=auth_headers, json=mapping)
    assert ok.status_code == 200, ok.text
    assert ok.json()["dataset"]["status"] == "ready"
    assert ok.json()["dataset"]["version"] == 2
    assert ok.json()["mapping"]["source"] == "user"
    assert client.get(f"{API}/datasets/{ds_id}/dashboard", headers=auth_headers).status_code == 200


def test_chart_urls_are_versioned_and_revalidated(
    client: TestClient, auth_headers, uploaded
) -> None:
    from app.viz.cache import RENDER_VERSION

    ds_id = uploaded["dataset"]["id"]
    items = client.get(f"{API}/datasets/{ds_id}/insights", headers=auth_headers).json()["items"]
    url = next(i["chart_url"] for i in items if i["chart_url"])
    assert url.endswith(f".png?v={RENDER_VERSION}")
    r = client.get(url, params={"theme": "dark"}, headers=auth_headers)
    assert r.status_code == 200 and "no-cache" in r.headers["cache-control"]
