"""Pipeline: loading, parsing, profiling, mapping, cleaning, quality."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from app.pipeline.cleaner import clean
from app.pipeline.loader import UnsupportedFileError, load_table
from app.pipeline.mapping import ColumnMapping, HeuristicMapper, MappingError, validate_mapping
from app.pipeline.parsing import detect_currency, looks_numeric, parse_dates, parse_numeric
from app.pipeline.profiler import profile_dataframe, sample_rows
from app.pipeline.quality import score_quality
from app.pipeline.service import run_pipeline


# ------------------------------------------------------------------ loading
def test_load_csv_and_excel_roundtrip(raw_df: pd.DataFrame) -> None:
    head = raw_df.head(50)
    from_csv = load_table(head.to_csv(index=False).encode(), "a.csv")
    buf = io.BytesIO()
    head.to_excel(buf, index=False)
    from_xlsx = load_table(buf.getvalue(), "a.xlsx")
    assert list(from_csv.columns) == list(head.columns)
    assert list(from_xlsx.columns) == list(head.columns)
    assert len(from_csv) == len(from_xlsx) == 50


def test_load_semicolon_csv() -> None:
    df = load_table(b"date;total\n2025-01-01;10\n2025-01-02;12\n", "x.csv")
    assert list(df.columns) == ["date", "total"]


@pytest.mark.parametrize(
    ("data", "name"), [(b"a,b\n1,2", "x.pdf"), (b"", "x.csv"), (b"onlyonecolumn\n1\n2", "x.csv")]
)
def test_load_rejects_bad_files(data: bytes, name: str) -> None:
    with pytest.raises(UnsupportedFileError):
        load_table(data, name)


# ------------------------------------------------------------------ parsing
def test_parse_numeric_strips_currency_and_handles_negatives() -> None:
    s = pd.Series(["Rs 1,250", "PKR 2,000.50", "(300)", "$45", "15%", "abc", None])
    out = parse_numeric(s).tolist()
    assert out[:5] == [1250.0, 2000.5, -300.0, 45.0, 15.0]
    assert pd.isna(out[5]) and pd.isna(out[6])


def test_looks_numeric_rejects_ids() -> None:
    s = pd.Series(["ORD-100231", "C10023", "Rs 1,200", "1,200.50", "12%"])
    assert looks_numeric(s).tolist() == [False, False, True, True, True]


def test_detect_currency() -> None:
    assert detect_currency(pd.Series(["Rs 100", "200"])) == "PKR"
    assert detect_currency(pd.Series([1.0, 2.0])) is None


def test_parse_dates_dayfirst() -> None:
    out = parse_dates(pd.Series(["13/01/2025", "14/01/2025", "25/12/2025"]))
    assert out.notna().all()
    assert out.iloc[0] == pd.Timestamp(2025, 1, 13)


# ------------------------------------------------------------------ profile + mapping
def test_profile_kinds(raw_df: pd.DataFrame) -> None:
    kinds = {c.name: c.kind for c in profile_dataframe(raw_df).columns}
    assert kinds["Order Date"] == "datetime"
    assert kinds["Total"] == "numeric"
    assert kinds["Qty"] == "numeric"
    assert kinds["City"] == "categorical"
    assert kinds["Customer ID"] != "numeric"
    assert kinds["Order ID"] != "numeric"


def test_sample_rows_are_five_string_rows(raw_df: pd.DataFrame) -> None:
    rows = sample_rows(raw_df)
    assert len(rows) == 5
    assert all(isinstance(v, str) for r in rows for v in r.values())


def test_heuristic_mapping(raw_df: pd.DataFrame) -> None:
    mapping = HeuristicMapper().map_columns(profile_dataframe(raw_df), sample_rows(raw_df))
    assert mapping.assigned() == {
        "date": "Order Date",
        "revenue": "Total",
        "quantity": "Qty",
        "product": "Product",
        "customer": "Customer ID",
        "region": "City",
        "order_id": "Order ID",
    }


@pytest.mark.parametrize(
    ("mapping", "msg"),
    [
        (ColumnMapping(date="Order Date"), "revenue"),
        (ColumnMapping(date="Order Date", revenue="Nope"), "Unknown"),
        (ColumnMapping(date="Order Date", revenue="Total", quantity="Total"), "one role"),
    ],
)
def test_validate_mapping_errors(raw_df: pd.DataFrame, mapping: ColumnMapping, msg: str) -> None:
    with pytest.raises(MappingError, match=msg):
        validate_mapping(mapping, list(raw_df.columns))


# ------------------------------------------------------------------ cleaning
def test_clean_frame(pipeline_result) -> None:
    df, report = pipeline_result.clean, pipeline_result.cleaning
    assert report.duplicates_removed == 40
    assert report.missing_date_dropped == 25
    assert report.missing_revenue_dropped > 0
    assert report.currency == "PKR" and report.has_time
    assert df["date"].notna().all() and df["revenue"].notna().all()
    assert df["revenue"].dtype == "float64"
    assert df["date"].is_monotonic_increasing
    for col in ("month", "weekday", "weekday_num", "hour", "unit_price", "discount_pct"):
        assert col in df.columns
    assert set(df["weekday"].unique()) <= {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    assert df["month"].str.match(r"^\d{4}-\d{2}$").all()


def test_clean_never_copies_pii(clean_df: pd.DataFrame) -> None:
    lowered = [c.lower() for c in clean_df.columns]
    assert not any(k in c for c in lowered for k in ("name", "email", "phone"))


def test_clean_minimal_dataset_without_optional_roles() -> None:
    raw = pd.DataFrame(
        {
            "Day": ["2025-01-01", "2025-01-01", "2025-01-02", None],
            "Sales": ["Rs 100", "Rs 100", "250", "10"],
        }
    )
    df, report = clean(raw, ColumnMapping(date="Day", revenue="Sales"))
    assert len(df) == 2 and report.duplicates_removed == 1 and report.missing_date_dropped == 1
    assert "hour" not in df.columns and df["revenue"].tolist() == [100.0, 250.0]


# ------------------------------------------------------------------ quality
def test_quality_score_good_sample(pipeline_result) -> None:
    q = pipeline_result.quality
    assert 85 <= q.score <= 100 and q.label in {"Excellent", "Good"}
    assert any("duplicate" in i.message for i in q.issues)


def test_quality_score_penalises_poor_data() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2025-01-01", "bad", None, "2025-01-05"] * 5,
            "amount": ["10", None, "x", "20"] * 5,
        }
    )
    result = run_pipeline(raw)
    assert result.quality.score < 60
    assert result.quality.label in {"Fair", "Poor"}
    messages = " ".join(i.message for i in result.quality.issues)
    assert "history" in messages and "customer" in messages


def test_score_quality_is_bounded(pipeline_result) -> None:
    q = score_quality(pipeline_result.cleaning, ColumnMapping(date="d", revenue="r"))
    assert 0 <= q.score <= 100
