"""Insight library: each analysis plus the engine and dashboard KPIs."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from app.insights.anomalies import anomalies, daily_revenue, detect_anomalies
from app.insights.base import InsightContext, compact_number, pct_change
from app.insights.cohorts import cohort_retention
from app.insights.correlations import correlations
from app.insights.dashboard import (
    kpi_cards,
    kpi_sparklines,
    revenue_trend_chart,
    split_period,
    summary_text,
)
from app.insights.engine import generate_insights
from app.insights.kpi import kpi_summary
from app.insights.patterns import daypart, weekday_time_pattern
from app.insights.products import top_products
from app.insights.rfm import rfm_segments, rfm_table
from app.insights.trend import monthly_trend


def test_engine_returns_sorted_scored_jsonable(clean_df, ctx) -> None:
    items = generate_insights(clean_df, ctx)
    assert 5 <= len(items) <= 10
    scores = [i.score for i in items]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 1 for s in scores)
    json.dumps([i.model_dump() for i in items])  # fully JSON-safe
    assert len({i.id for i in items}) == len(items)


def test_engine_category_filter(clean_df, ctx) -> None:
    items = generate_insights(clean_df, ctx, category="customers")
    assert items and all(i.category == "customers" for i in items)


def test_engine_survives_minimal_dataset() -> None:
    dates = pd.date_range("2025-01-01", periods=120, freq="D")
    df = pd.DataFrame({"date": dates, "revenue": np.linspace(100, 200, 120)})
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["weekday_num"] = df["date"].dt.weekday
    df["weekday"] = df["weekday_num"].map(
        dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
    )
    items = generate_insights(df, InsightContext())
    kinds = {i.kind for i in items}
    assert "monthly_trend" in kinds
    assert not kinds & {"rfm_segments", "cohort_retention", "top_products"}


def test_kpi_summary(clean_df, ctx) -> None:
    i = kpi_summary(clean_df, ctx)
    assert i is not None and i.category == "sales"
    assert set(i.data["current"]) == {"revenue", "orders", "avg_order_value", "active_customers"}
    assert i.data["month"] > i.data["previous_month"]


def test_monthly_trend_detects_growth(clean_df, ctx) -> None:
    i = monthly_trend(clean_df, ctx)
    assert i is not None and i.chart is not None and i.chart.kind == "line"
    assert len(i.data["months"]) == len(i.data["revenue"]) >= 3


def test_top_products(clean_df, ctx) -> None:
    i = top_products(clean_df, ctx)
    assert i is not None
    shares = [p["share"] for p in i.data["top"]]
    assert shares == sorted(shares, reverse=True)
    assert 0 < i.data["top3_share"] <= 1 and i.data["product_count"] == 20


def test_weekday_time_pattern(clean_df, ctx) -> None:
    i = weekday_time_pattern(clean_df, ctx)
    assert i is not None and i.chart.kind == "heatmap"
    assert len(i.chart.payload["values"]) == 7 and len(i.chart.payload["values"][0]) == 4
    assert i.data["lift"] >= 1
    assert [daypart(h) for h in (7, 13, 19, 2)] == ["Morning", "Afternoon", "Evening", "Night"]


def test_rfm_segments(clean_df, ctx) -> None:
    table = rfm_table(clean_df)
    assert table["r"].between(1, 5).all() and table["f"].between(1, 5).all()
    i = rfm_segments(clean_df, ctx)
    assert i is not None and i.chart.kind == "donut"
    assert sum(s["customers"] for s in i.data["segments"]) == i.data["customer_count"]


def test_anomalies_finds_planted_spike(clean_df, ctx) -> None:
    i = anomalies(clean_df, ctx)
    assert i is not None and i.category == "anomalies"
    dates = [a["date"] for a in i.data["anomalies"]]
    assert "2026-04-18" in dates
    spike = next(a for a in i.data["anomalies"] if a["date"] == "2026-04-18")
    assert spike["type"] == "spike" and spike["z"] > 3


def test_anomaly_band_excludes_past_spikes() -> None:
    s = pd.Series(
        100.0 + np.tile([0, 5, -5, 3], 30), index=pd.date_range("2025-01-01", periods=120, freq="D")
    )
    s.iloc[60] = 5000
    bands = detect_anomalies(s)
    assert bool(bands["is_anomaly"].iloc[60])
    # The day after the spike still has a tight band (spike excluded from the window).
    assert bands["upper"].iloc[65] < 200


def test_daily_revenue_fills_gaps() -> None:
    df = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01", "2025-01-04"]), "revenue": [10.0, 20.0]}
    )
    assert daily_revenue(df).tolist() == [10.0, 0.0, 0.0, 20.0]


def test_correlations_none_when_weak_and_found_when_strong(clean_df, ctx) -> None:
    df = clean_df.copy()
    rng = np.random.default_rng(0)
    df["ad_spend"] = df["discount_pct"] * 3 + rng.normal(0, 1, len(df))
    i = correlations(df, ctx)
    assert i is not None and set(i.data["pair"]) == {"discount_pct", "ad_spend"}
    assert i.data["r"] > 0.9 and i.chart.kind == "corr_heatmap"


def test_cohort_retention(clean_df, ctx) -> None:
    i = cohort_retention(clean_df, ctx)
    assert i is not None
    assert 0 < i.data["month1_retention"] < 1
    flat = [v for row in i.data["matrix_pct"] for v in row if v is not None]
    assert all(0 <= v <= 100 for v in flat)
    assert i.chart.payload["cols"][0] == "M1"


def test_split_period_and_kpis(clean_df, ctx) -> None:
    cur, prev, window = split_period(clean_df, "30d")
    assert window.end == clean_df["date"].max().date().isoformat()
    assert cur["date"].min() >= pd.Timestamp(window.start)
    assert prev["date"].max() < pd.Timestamp(window.start)
    cards = kpi_cards(cur, prev, ctx.currency)
    assert [c.key for c in cards] == ["revenue", "orders", "avg_order_value", "active_customers"]
    rev = cards[0]
    assert rev.change_pct == pct_change(cur["revenue"].sum(), prev["revenue"].sum())
    assert rev.display.startswith("PKR ")
    chart = revenue_trend_chart(clean_df, cur, "30d", ctx.currency)
    assert chart is not None and len(chart.payload["x"]) == 30
    assert "Revenue was" in summary_text(cards, "30d", None)


def test_one_year_period_uses_weekly_points(clean_df, ctx) -> None:
    cur, _, _ = split_period(clean_df, "1y")
    chart = revenue_trend_chart(clean_df, cur, "1y", ctx.currency)
    assert 25 <= len(chart.payload["x"]) <= 54


def test_formatting_helpers() -> None:
    assert compact_number(1_234_567) == "1.2M"
    assert compact_number(45_300) == "45.3K"
    assert pct_change(110, 100) == 10.0
    assert pct_change(5, 0) is None


def test_weekly_totals_anchor_on_last_or_first_day() -> None:
    from app.insights.base import weekly_totals

    s = pd.Series(1.0, index=pd.date_range("2026-01-01", periods=17, freq="D"))
    end = weekly_totals(s, anchor="end")
    assert end.index[-1] == s.index[-1] and end.tolist() == [7.0, 7.0]  # 3 oldest days dropped
    start = weekly_totals(s, anchor="start")
    assert start.index[0] == pd.Timestamp("2026-01-07") and start.tolist() == [7.0, 7.0]


def test_one_year_chart_ends_on_last_data_day(clean_df, ctx) -> None:
    cur, _, _ = split_period(clean_df, "1y")
    fc_dates = pd.date_range(clean_df["date"].max().normalize() + pd.Timedelta(days=1), periods=90)
    forecast = {
        "dates": [d.date().isoformat() for d in fc_dates],
        "yhat": [1.0] * 90,
        "lower": [0.5] * 90,
        "upper": [1.5] * 90,
    }
    chart = revenue_trend_chart(clean_df, cur, "1y", ctx.currency, forecast)
    last = clean_df["date"].max().strftime("%Y-%m-%d")
    assert chart.payload["x"][-1] == last and chart.payload["today"] == last
    assert chart.payload["series"][1]["x"][0] == last  # forecast joins the last actual


def test_partial_previous_period_has_no_change(clean_df, ctx) -> None:
    # Keep 150 days: the 90 days before the last 90 are then only partly covered.
    recent = clean_df[clean_df["date"] > clean_df["date"].max() - pd.Timedelta(days=150)]
    cur, prev, window = split_period(recent, "90d")
    assert window.previous_complete is False and len(prev) > 0
    cards = kpi_cards(cur, prev, ctx.currency, comparable=window.previous_complete)
    assert all(c.change_pct is None and c.previous is None for c in cards)
    _, _, w30 = split_period(clean_df, "30d")
    assert w30.previous_complete is True


def test_kpi_sparklines_match_totals(clean_df) -> None:
    for period, points in (("7d", 7), ("30d", 30), ("90d", 12), ("1y", 26)):
        cur, _, window = split_period(clean_df, period)
        sparks = kpi_sparklines(cur, window, period)
        assert set(sparks) == {"revenue", "orders", "avg_order_value", "active_customers"}
        assert len(sparks["revenue"]) == points
        assert sum(sparks["revenue"]) == pytest.approx(cur["revenue"].sum(), rel=1e-6)
