"""Monthly report: month choice, the numbers it shows, and the PDF endpoint."""

from __future__ import annotations

import pandas as pd
import pytest

from app.reports.monthly import ReportError, available_months, build_report, default_month
from app.reports.pdf import render_pdf


def latest_month(df: pd.DataFrame) -> str:
    return default_month(df)


def test_default_month_is_the_latest_complete_one(clean_df) -> None:
    last = clean_df["date"].max()
    complete = last.day >= last.days_in_month - 1
    expected = last.to_period("M") - (0 if complete else 1)
    assert default_month(clean_df) == str(expected)
    assert default_month(clean_df) in available_months(clean_df)


@pytest.mark.parametrize(
    ("last_day", "expected"),
    [("2017-12-30", "2017-12"), ("2017-12-31", "2017-12"), ("2017-12-20", "2017-11")],
)
def test_nearly_complete_month_counts(last_day: str, expected: str) -> None:
    df = pd.DataFrame({"date": pd.to_datetime(["2017-10-05", "2017-11-15", last_day])})
    assert default_month(df) == expected


def test_report_numbers_match_the_data(clean_df) -> None:
    month = latest_month(clean_df)
    report = build_report(clean_df, month, dataset_name="My shop", currency="PKR")
    cur = clean_df[clean_df["date"].dt.to_period("M") == pd.Period(month)]
    revenue = next(k for k in report.kpis if k.label == "Revenue")
    assert revenue.value == pytest.approx(cur["revenue"].sum(), rel=1e-9)
    prev = clean_df[clean_df["date"].dt.to_period("M") == pd.Period(month) - 1]["revenue"].sum()
    assert revenue.vs_prev == pytest.approx((cur["revenue"].sum() - prev) / prev * 100, abs=0.06)
    assert report.headline.startswith("Revenue in ")
    titles = [c.title for c in report.charts]
    assert {"Revenue by day", "Last 12 months", "Top products", "Sales by weekday"} <= set(titles)
    assert report.customers and int(report.customers["New this month"].replace(",", "")) >= 0


def test_month_without_data_is_explained(clean_df) -> None:
    with pytest.raises(ReportError, match="no data"):
        build_report(clean_df, "1999-01", dataset_name="x", currency=None)
    with pytest.raises(ReportError):
        build_report(clean_df, "not-a-month", dataset_name="x", currency=None)


def test_pdf_is_a_real_multi_page_document(clean_df) -> None:
    report = build_report(
        clean_df,
        latest_month(clean_df),
        dataset_name="My shop",
        currency="PKR",
        profile={"row_count": 100, "column_count": 3, "columns": [{"name": "Total"}]},
        quality={"score": 92, "label": "Excellent", "issues": [{"message": "A few blanks"}]},
        actions=[{"title": "Do a thing", "detail": "Because <reasons> & more"}],
    )
    pdf = render_pdf(report)
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    assert pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") >= 3


def test_report_endpoints(client, auth_headers, uploaded) -> None:
    ds = uploaded["dataset"]["id"]
    months = client.get(f"/api/v1/datasets/{ds}/report/months", headers=auth_headers).json()
    assert months["default"] in [m["month"] for m in months["months"]]
    r = client.get(f"/api/v1/datasets/{ds}/report", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert r.headers["content-disposition"].endswith(f'-{months["default"]}.pdf"')
    missing = client.get(f"/api/v1/datasets/{ds}/report?month=1999-01", headers=auth_headers)
    assert missing.status_code == 422 and "no data" in missing.json()["detail"]
    assert client.get(f"/api/v1/datasets/{ds}/report").status_code == 401
