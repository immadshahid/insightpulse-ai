"""Google Sheets import (link checks, redirects) and dataset deletion."""

from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.core.sheets import SheetError, export_url, fetch_sheet

ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
LINK = f"https://docs.google.com/spreadsheets/d/{ID}/edit?usp=sharing#gid=42"


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_export_url_keeps_only_id_and_tab() -> None:
    assert export_url(LINK).endswith(f"/d/{ID}/export?format=csv&gid=42")


@pytest.mark.parametrize(
    "link",
    [
        "http://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
        "https://evil.example/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
        "https://docs.google.com.evil.example/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_other_addresses_are_refused(link: str) -> None:
    with pytest.raises(SheetError):
        fetch_sheet(link, 1000, client_for(lambda r: httpx.Response(200, content=b"secret")))


def test_follows_google_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "docs.google.com":
            location = "https://doc-0.googleusercontent.com/export"
            return httpx.Response(307, headers={"location": location})
        return httpx.Response(200, headers={"content-type": "text/csv"}, content=b"a,b\n1,2\n")

    assert fetch_sheet(LINK, 1000, client_for(handler)) == b"a,b\n1,2\n"


def test_redirect_off_google_is_refused() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})

    with pytest.raises(SheetError, match="safely"):
        fetch_sheet(LINK, 1000, client_for(handler))


def test_private_sheet_explains_sharing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://accounts.google.com/login"})

    with pytest.raises(SheetError, match="Anyone with the link"):
        fetch_sheet(LINK, 1000, client_for(handler))


def test_too_large_is_refused() -> None:
    client = client_for(lambda r: httpx.Response(200, content=b"x" * 2000))
    with pytest.raises(SheetError, match="larger"):
        fetch_sheet(LINK, 1000, client)


def test_import_endpoint_builds_a_dataset(client, auth_headers, raw_csv, monkeypatch) -> None:
    monkeypatch.setattr("app.api.datasets.fetch_sheet", lambda url, limit: raw_csv)
    r = client.post(
        "/api/v1/datasets/import-sheet",
        headers=auth_headers,
        json={"url": LINK, "name": "Orders sheet"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["dataset"]["name"] == "Orders sheet"


def test_import_endpoint_reports_bad_link(client, auth_headers) -> None:
    r = client.post(
        "/api/v1/datasets/import-sheet", headers=auth_headers, json={"url": "https://x.example/a"}
    )
    assert r.status_code == 400 and "Google Sheets" in r.json()["detail"]


def test_delete_removes_dataset_and_files(client, auth_headers, other_headers, raw_csv) -> None:
    from pathlib import Path

    r = client.post(
        "/api/v1/datasets",
        headers=auth_headers,
        files={"file": ("gone.csv", raw_csv, "text/csv")},
    )
    ds = r.json()["dataset"]["id"]
    assert client.get(f"/api/v1/datasets/{ds}/insights", headers=auth_headers).status_code == 200
    folder = Path(get_settings().storage_dir) / "datasets" / ds
    assert any(folder.iterdir())

    assert client.delete(f"/api/v1/datasets/{ds}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/v1/datasets/{ds}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/v1/datasets/{ds}/profile", headers=auth_headers).status_code == 404
    assert not folder.exists()


def test_sample_data_can_be_loaded(client, auth_headers) -> None:
    r = client.post("/api/v1/datasets/sample", headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["dataset"]["name"] == "Sample shop"
    assert r.json()["dataset"]["status"] == "ready"
