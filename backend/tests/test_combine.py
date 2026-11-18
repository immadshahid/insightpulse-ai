"""Multi-file analysis: stacking files with the same columns and joining related files."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.combine import CombineError, Table, join, preview, stack
from tests.conftest import _register

API = "/api/v1"


def orders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": range(1, 201),
            "Order Date": pd.date_range("2026-01-01", periods=200, freq="D").astype(str),
            "customer_id": [100 + i % 20 for i in range(200)],
            "SKU": [f"P-{i % 5}" for i in range(200)],
            "Total": [50.0 + i for i in range(200)],
        }
    )


def customers() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Customer ID": [float(100 + i) for i in range(18)],  # 2 customers are unknown
            "City": ["Lahore" if i % 2 else "Karachi" for i in range(18)],
            "Total": range(18),  # clashes with the orders column name
        }
    )


def products() -> pd.DataFrame:
    return pd.DataFrame(
        {"sku": [f"p-{i} " for i in range(5)], "Category": ["A", "B", "A", "C", "B"]}
    )


# ------------------------------------------------------------------ stack


def test_stack_matches_columns_and_keeps_the_source() -> None:
    jan = pd.DataFrame({"Order Date": ["2026-01-02"], "Total": [10], "City": ["Lahore"]})
    feb = pd.DataFrame({"order_date": ["2026-02-03"], "TOTAL": [20], "city": ["Karachi"]})
    out = stack([Table("Jan", jan), Table("Feb", feb)])
    assert list(out.columns) == ["Order Date", "Total", "City", "Source file"]
    assert out["Total"].tolist() == [10, 20] and out["Source file"].tolist() == ["Jan", "Feb"]


def test_stack_keeps_columns_only_some_files_have() -> None:
    a = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
    b = pd.DataFrame({"a": [4], "b": [5], "c": [6], "extra": [7]})
    plan = preview([Table("A", a), Table("B", b)])["stack"]
    assert plan.possible and plan.partial_columns == ["extra"] and plan.rows == 2
    out = stack([Table("A", a), Table("B", b)])
    assert pd.isna(out.loc[0, "extra"]) and out.loc[1, "extra"] == 7


def test_different_files_cannot_be_stacked() -> None:
    result = preview([Table("Orders", orders()), Table("Customers", customers())])
    assert not result["stack"].possible and result["suggested"] == "join"
    with pytest.raises(CombineError):
        stack([Table("Orders", orders()), Table("Customers", customers())])


# ------------------------------------------------------------------ join


def test_join_finds_the_keys_and_keeps_every_order() -> None:
    tables = [
        Table("Customers", customers()),
        Table("Orders", orders()),
        Table("Products", products()),
    ]
    out, plan = join(tables)
    assert plan.base == "Orders" and len(out) == 200
    links = {(s.right, s.left_column, s.right_column) for s in plan.steps}
    assert links == {("Customers", "customer_id", "Customer ID"), ("Products", "SKU", "sku")}
    assert out["Category"].notna().all()  # ' p-1 ' matched 'P-1'
    assert out["City"].isna().sum() == 20  # customers 118 and 119 are not in the lookup
    assert "Total (Customers)" in out.columns and out["Total"].iloc[0] == 50.0
    step = next(s for s in plan.steps if s.right == "Customers")
    assert step.match_pct == 90.0


def test_number_columns_with_unrelated_names_are_not_linked() -> None:
    other = pd.DataFrame({"rank": range(1, 300), "label": [f"x{i}" for i in range(1, 300)]})
    plan = preview([Table("Orders", orders()), Table("Other", other)])["join"]
    assert not plan.possible and "Other" in plan.reason


def test_a_key_that_repeats_in_the_lookup_is_not_used() -> None:
    repeated = pd.concat([customers(), customers()], ignore_index=True)
    plan = preview([Table("Orders", orders()), Table("Customers", repeated)])["join"]
    assert not plan.possible


def test_combining_needs_two_tables() -> None:
    with pytest.raises(CombineError):
        preview([Table("Orders", orders())])


# ------------------------------------------------------------------ API


def upload(client, headers, name: str, df: pd.DataFrame) -> str:
    r = client.post(
        f"{API}/datasets",
        headers=headers,
        files={"file": (f"{name}.csv", df.to_csv(index=False).encode(), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["dataset"]["id"]


@pytest.fixture(scope="module")
def user(client) -> dict[str, str]:
    return _register(client, "combine@example.com")


def test_join_api_builds_a_sales_dataset(client, user) -> None:
    ids = [upload(client, user, "Orders", orders()), upload(client, user, "Customers", customers())]
    p = client.post(f"{API}/datasets/combine/preview", headers=user, json={"dataset_ids": ids})
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["suggested"] == "join" and body["join"]["rows"] == 200
    assert body["join"]["steps"][0]["right_column"] == "Customer ID"

    r = client.post(
        f"{API}/datasets/combine", headers=user, json={"dataset_ids": ids, "mode": "join"}
    )
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["dataset"]["name"] == "Orders + Customers" and made["dataset"]["kind"] == "sales"
    assert made["mapping"]["region"] == "City"  # the joined column is usable right away
    dash = client.get(f"{API}/datasets/{made['dataset']['id']}/dashboard", headers=user)
    assert dash.status_code == 200
    assert len(client.get(f"{API}/datasets", headers=user).json()) == 3  # originals are kept


def test_stack_api_and_errors(client, user, other_headers) -> None:
    first, second = orders().iloc[:100], orders().iloc[100:]
    ids = [upload(client, user, "H1", first), upload(client, user, "H2", second)]
    r = client.post(
        f"{API}/datasets/combine",
        headers=user,
        json={"dataset_ids": ids, "mode": "stack", "name": "Full year"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["dataset"]["name"] == "Full year" and r.json()["dataset"]["row_count"] == 200
    assert "Source file" in [c["name"] for c in r.json()["profile"]["columns"]]

    customers_id = upload(client, user, "Customers", customers())
    bad = client.post(
        f"{API}/datasets/combine",
        headers=user,
        json={"dataset_ids": [ids[0], customers_id], "mode": "stack"},
    )
    assert bad.status_code == 422 and "same columns" in bad.json()["detail"]
    twice = client.post(
        f"{API}/datasets/combine/preview", headers=user, json={"dataset_ids": [ids[0], ids[0]]}
    )
    assert twice.status_code == 422
    stranger = client.post(
        f"{API}/datasets/combine/preview", headers=other_headers, json={"dataset_ids": ids}
    )
    assert stranger.status_code == 404
