"""Shared fixtures. Tests use SQLite + a temp storage dir, so no Docker is needed."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="ip_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["JWT_SECRET"] = "test-secret-not-for-production-use-0123456789"

from fastapi.testclient import TestClient  # noqa: E402

from app.insights.base import InsightContext  # noqa: E402
from app.pipeline.service import PipelineResult, run_pipeline  # noqa: E402
from sample_data.generate_sample import generate  # noqa: E402


@pytest.fixture(scope="session")
def raw_df() -> pd.DataFrame:
    """~8 months of messy synthetic sales including the 18 Apr 2026 spike."""
    return generate(
        start=date(2025, 11, 1), months=8, base_orders_per_day=14, n_customers=450, seed=7
    )


@pytest.fixture(scope="session")
def raw_csv(raw_df: pd.DataFrame) -> bytes:
    """The raw sample as CSV bytes (what a user would upload)."""
    return raw_df.to_csv(index=False).encode()


@pytest.fixture(scope="session")
def pipeline_result(raw_df: pd.DataFrame) -> PipelineResult:
    """Full pipeline output for the sample."""
    return run_pipeline(raw_df)


@pytest.fixture(scope="session")
def clean_df(pipeline_result: PipelineResult) -> pd.DataFrame:
    """Cleaned canonical frame."""
    return pipeline_result.clean


@pytest.fixture(scope="session")
def ctx(pipeline_result: PipelineResult) -> InsightContext:
    """Insight context for the sample."""
    return InsightContext.from_frame(pipeline_result.clean, pipeline_result.cleaning.currency)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """API client with tables created via the app lifespan."""
    from app.main import app

    with TestClient(app) as c:
        yield c


def _register(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "s3cret-pass"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def auth_headers(client: TestClient) -> dict[str, str]:
    """Bearer header for a primary test user."""
    return _register(client, "owner@example.com")


@pytest.fixture(scope="session")
def other_headers(client: TestClient) -> dict[str, str]:
    """Bearer header for a second user (for ownership checks)."""
    return _register(client, "intruder@example.com")


@pytest.fixture(scope="session")
def uploaded(client: TestClient, auth_headers: dict[str, str], raw_csv: bytes) -> dict:
    """Upload the sample once and return the profile response."""
    r = client.post(
        "/api/v1/datasets",
        headers=auth_headers,
        files={"file": ("sales.csv", raw_csv, "text/csv")},
        data={"name": "My shop"},
    )
    assert r.status_code == 201, r.text
    return r.json()
