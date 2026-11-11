"""ML API: forecast jobs, job status, churn, what-if, segments, Home forecast overlay."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def _ds(uploaded: dict) -> str:
    return uploaded["dataset"]["id"]


def test_forecast_job_lifecycle(client: TestClient, auth_headers, uploaded) -> None:
    ds = _ds(uploaded)
    body = {"target": "orders", "horizon_days": 30}
    r = client.post(f"{API}/datasets/{ds}/forecast", json=body, headers=auth_headers)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "forecast" and job["params"] == body
    # TestClient runs background tasks before returning, so the job is done now.
    done = client.get(f"{API}/jobs/{job['id']}", headers=auth_headers).json()
    assert done["status"] == "succeeded", done
    result = done["result"]
    assert len(result["yhat"]) == 30 and result["target"] == "orders"
    assert result["model"] in {"prophet", "sarima", "xgboost"}
    assert result["accuracy_note"].startswith("Within")
    png = client.get(result["chart_url"], headers=auth_headers)
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    # Same request on the same data version reuses the finished job.
    again = client.post(f"{API}/datasets/{ds}/forecast", json=body, headers=auth_headers)
    assert again.json()["id"] == job["id"] and again.json()["status"] == "succeeded"


def test_forecast_validation(client: TestClient, auth_headers, uploaded) -> None:
    ds = _ds(uploaded)
    for bad in ({"horizon_days": 3}, {"horizon_days": 400}, {"target": "profit"}):
        r = client.post(f"{API}/datasets/{ds}/forecast", json=bad, headers=auth_headers)
        assert r.status_code == 422


def test_jobs_are_private(client: TestClient, auth_headers, other_headers, uploaded) -> None:
    ds = _ds(uploaded)
    r = client.post(
        f"{API}/datasets/{ds}/forecast",
        json={"target": "orders", "horizon_days": 30},
        headers=auth_headers,
    )
    job_id = r.json()["id"]
    assert client.get(f"{API}/jobs/{job_id}", headers=other_headers).status_code == 404
    assert client.get(f"{API}/jobs/nope", headers=auth_headers).status_code == 404
    assert (
        client.post(f"{API}/datasets/{ds}/forecast", json={}, headers=other_headers).status_code
        == 404
    )


def test_dashboard_includes_forecast_once_ready(client: TestClient, auth_headers, uploaded) -> None:
    ds = _ds(uploaded)
    first = client.get(
        f"{API}/datasets/{ds}/dashboard", params={"period": "30d"}, headers=auth_headers
    ).json()
    assert first["forecast"]["status"] in {"pending", "ready"}
    second = client.get(
        f"{API}/datasets/{ds}/dashboard", params={"period": "30d"}, headers=auth_headers
    ).json()
    assert second["forecast"]["status"] == "ready"
    assert second["forecast"]["accuracy_note"].startswith("Within")
    png = client.get(second["charts"]["revenue_trend"], headers=auth_headers)
    assert png.status_code == 200
    # The Forecast screen's default request reuses the Home job.
    r = client.post(f"{API}/datasets/{ds}/forecast", json={}, headers=auth_headers)
    assert r.json()["id"] == second["forecast"]["job_id"]


def test_churn_endpoint(client: TestClient, auth_headers, uploaded) -> None:
    r = client.post(f"{API}/datasets/{_ds(uploaded)}/predict/churn", json={}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0.5 < body["roc_auc"] <= 1 and body["model"] == "random_forest"
    assert body["chart_url"].startswith(f"{API}/charts/")
    custom = client.post(
        f"{API}/datasets/{_ds(uploaded)}/predict/churn",
        json={"churn_days": 45},
        headers=auth_headers,
    ).json()
    assert custom["churn_window_days"] == 45


def test_whatif_endpoint_slider(client: TestClient, auth_headers, uploaded) -> None:
    ds = _ds(uploaded)
    results = {}
    for change in (-10, 0, 10):
        r = client.post(
            f"{API}/datasets/{ds}/whatif",
            json={"lever": "price", "change_pct": change},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        results[change] = r.json()
    assert results[10]["units_change_pct"] < 0 < results[-10]["units_change_pct"]
    assert results[0]["revenue_change_pct"] == 0
    assert (
        client.post(
            f"{API}/datasets/{ds}/whatif", json={"change_pct": 50}, headers=auth_headers
        ).status_code
        == 422
    )


def test_segments_endpoint(client: TestClient, auth_headers, uploaded) -> None:
    r = client.get(f"{API}/datasets/{_ds(uploaded)}/segments", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert 3 <= body["k"] <= 6 and body["segments"][0]["name"]
    assert client.get(body["chart_url"], headers=auth_headers).status_code == 200
