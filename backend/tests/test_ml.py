"""ML: forecasting (shape, holdout, selection, fallback), churn, segments, what-if, store."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.storage import LocalStorage
from app.ml.calendar import eid_proximity, pakistan_holidays
from app.ml.churn import ChurnUnavailableError, customer_features, train_churn
from app.ml.forecast import (
    forecast,
    forecast_chart_spec,
    human_span,
    mape,
    total_band_half_width,
    weekly_blocks,
)
from app.ml.models import CANDIDATES
from app.ml.segments import kmeans_segments
from app.ml.series import TargetError, available_targets, daily_series
from app.ml.store import load_model, save_model
from app.ml.whatif import WhatIfUnavailableError, run_scenario, train_whatif
from app.viz.charts import render_chart


@pytest.fixture(scope="module")
def full_forecast(clean_df):
    """One auto-selected 30-day revenue forecast (all three candidates)."""
    return forecast(clean_df, "revenue", 30)


# ------------------------------------------------------------------ series + calendar
def test_daily_series_is_continuous(clean_df) -> None:
    s = daily_series(clean_df, "revenue")
    assert s.index.freqstr == "D" and s.notna().all()
    assert s.sum() == pytest.approx(clean_df["revenue"].sum())
    assert set(available_targets(clean_df)) == {"revenue", "orders", "quantity"}
    with pytest.raises(TargetError):
        daily_series(clean_df.drop(columns=["quantity"]), "quantity")


def test_pakistan_holidays_include_eids() -> None:
    hol = pakistan_holidays(2025, 2026)
    assert {"Eid-ul-Fitr", "Eid-ul-Adha"} <= set(hol["holiday"])
    eid = hol[hol["holiday"] == "Eid-ul-Fitr"].iloc[0]
    assert eid["lower_window"] < 0  # shopping build-up before Eid
    prox = eid_proximity(pd.date_range("2026-03-01", "2026-03-31"))
    assert prox.max() == 1.0 and prox.min() == 0.0


# ------------------------------------------------------------------ forecasting
def test_forecast_has_right_shape(full_forecast) -> None:
    result, model = full_forecast
    assert len(result.dates) == len(result.yhat) == len(result.lower) == len(result.upper) == 30
    lo, mid, hi = map(np.asarray, (result.lower, result.yhat, result.upper))
    assert (lo <= mid).all() and (mid <= hi).all() and (lo >= 0).all()
    assert pd.Timestamp(result.dates[0]) == pd.Timestamp(result.last_date) + pd.Timedelta(days=1)
    assert result.total_lower <= result.total <= result.total_upper
    assert result.model in CANDIDATES and model.name == result.model


def test_forecast_uses_time_based_holdout_and_picks_lowest_mape(full_forecast) -> None:
    result, _ = full_forecast
    assert result.holdout_days == round(result.history_days * 0.2)
    assert pd.Timestamp(result.holdout_start) > pd.Timestamp(result.train_end)
    assert pd.Timestamp(result.holdout_start) == pd.Timestamp(result.last_date) - pd.Timedelta(
        days=result.holdout_days - 1
    )
    scored = [s for s in result.models_tried if s.ok]
    assert {s.model for s in result.models_tried} == {"prophet", "sarima", "xgboost"}
    assert result.model == min(scored, key=lambda s: s.weekly_mape).model
    assert result.accuracy_note.startswith("Within ±")


def test_short_history_falls_back_to_trend(clean_df) -> None:
    short = clean_df[clean_df["date"] < clean_df["date"].min() + pd.Timedelta(days=40)]
    result, model = forecast(short, "revenue", 30)
    assert result.model == "trend" and model.name == "trend"
    assert "more data" in result.message or "60 days" in result.message
    assert len(result.yhat) == 30 and result.accuracy_pct is None


def test_too_little_data_raises(clean_df) -> None:
    tiny = clean_df[clean_df["date"] < clean_df["date"].min() + pd.Timedelta(days=5)]
    with pytest.raises(ValueError, match="at least"):
        forecast(tiny, "revenue", 30)


@pytest.mark.parametrize("name", sorted(CANDIDATES))
def test_each_candidate_predicts_horizon(clean_df, name: str) -> None:
    y = daily_series(clean_df, "orders")
    fc = CANDIDATES[name]().fit(y).predict(14)
    assert list(fc.columns) == ["yhat", "lower", "upper"] and len(fc) == 14
    assert fc.index[0] == y.index[-1] + pd.Timedelta(days=1)


def test_forecast_metric_helpers() -> None:
    assert mape(np.array([100.0, 0.0, 50.0]), np.array([110.0, 5.0, 50.0])) == pytest.approx(5.0)
    assert weekly_blocks(np.arange(16.0)).tolist() == [21.0, 70.0]
    assert human_span(110) == "4 months" and human_span(21) == "3 weeks"
    fc = pd.DataFrame({"yhat": [10.0] * 14, "lower": [8.0] * 14, "upper": [12.0] * 14})
    # Two independent weekly blocks of 7 x 2 => sqrt(14^2 + 14^2)
    assert total_band_half_width(fc) == pytest.approx(np.sqrt(2) * 14)
    # Measured accuracy widens it: 9% weekly MAPE over 2 weeks -> 1.2816 * 1.25 * 9% / sqrt(2)
    assert total_band_half_width(fc, weekly_mape_pct=9.0) == pytest.approx(np.sqrt(2) * 14)
    tight = fc.assign(lower=9.9, upper=10.1)  # model band narrower than measured error
    wide = total_band_half_width(tight, weekly_mape_pct=9.0)
    assert wide == pytest.approx(1.2816 * 1.25 * 0.09 / np.sqrt(2) * 140)
    # Long horizons stop shrinking after a month (errors persist).
    long_fc = pd.concat([tight] * 26, ignore_index=True)
    rel = total_band_half_width(long_fc, 9.0) / long_fc["yhat"].sum()
    assert rel == pytest.approx(1.2816 * 1.25 * 0.09 / 2)


@pytest.mark.parametrize("horizon", [30, 365])
def test_forecast_chart_renders(full_forecast, horizon: int) -> None:
    result, _ = full_forecast
    spec = forecast_chart_spec(result.model_copy(update={"horizon_days": horizon}), "PKR")
    assert spec.payload["today"] == result.last_date
    assert [s["role"] for s in spec.payload["series"]] == ["actual", "forecast"]
    for theme in ("light", "dark"):
        assert render_chart(spec.kind, spec.payload, theme)[:4] == b"\x89PNG"


# ------------------------------------------------------------------ churn
def test_churn_model(clean_df) -> None:
    result, model = train_churn(clean_df)
    assert 0.5 < result.roc_auc <= 1.0
    assert 0 < result.base_churn_rate < 1
    assert sum(result.risk_bands.values()) == result.customers_scored
    assert all(0 <= c.probability <= 1 for c in result.top_at_risk)
    assert model.class_weight == "balanced"
    assert result.feature_importance[0]["importance"] >= result.feature_importance[-1]["importance"]


def test_churn_features_have_no_lookahead(clean_df) -> None:
    cutoff = clean_df["date"].max() - pd.Timedelta(days=60)
    feats = customer_features(clean_df, cutoff)
    assert (feats["recency_days"] >= 0).all()
    late = set(clean_df.loc[clean_df["date"] >= cutoff, "customer"]) - set(
        clean_df.loc[clean_df["date"] < cutoff, "customer"]
    )
    assert not late & set(feats.index)  # customers first seen after cutoff are excluded


def test_churn_needs_customers(clean_df) -> None:
    with pytest.raises(ChurnUnavailableError):
        train_churn(clean_df.drop(columns=["customer"]))


# ------------------------------------------------------------------ segments
def test_kmeans_segments(clean_df) -> None:
    result, model = kmeans_segments(clean_df)
    assert 3 <= result.k <= 6 and model.n_clusters == result.k
    assert sum(s.customers for s in result.segments) == clean_df["customer"].nunique()
    assert sum(s.revenue_share for s in result.segments) == pytest.approx(1.0, abs=1e-3)
    names = [s.name for s in result.segments]
    assert "VIP" in names and len(set(names)) == len(names)


# ------------------------------------------------------------------ what-if
@pytest.fixture(scope="module")
def whatif_model(clean_df):
    return train_whatif(clean_df)


def test_whatif_price_increase_lowers_units(whatif_model) -> None:
    up = run_scenario(whatif_model, "price", 10)
    down = run_scenario(whatif_model, "price", -10)
    assert up.units_change_pct < 0 < down.units_change_pct
    assert up.implied_elasticity < 0
    assert run_scenario(whatif_model, "price", 0).revenue_change_pct == pytest.approx(0)
    labels = [f["label"] for f in up.shap_importance]
    assert "Price vs usual" in labels and "Discount" in labels


def test_whatif_discount_raises_units(whatif_model) -> None:
    more = run_scenario(whatif_model, "discount", 5)
    assert more.units_change_pct > 0
    assert any("same number of orders" in n for n in more.notes)


def test_whatif_requires_quantity(clean_df) -> None:
    with pytest.raises(WhatIfUnavailableError):
        train_whatif(clean_df.drop(columns=["quantity"]))


# ------------------------------------------------------------------ model store
def test_model_store_roundtrip(tmp_path, whatif_model) -> None:
    storage = LocalStorage(tmp_path)
    key = save_model(storage, "ds1", 3, "whatif", whatif_model, whatif_model.metrics)
    assert key.endswith(".joblib") and storage.exists("models/ds1/v3/whatif.metrics.json")
    bundle = load_model(storage, "ds1", 3, "whatif")
    assert bundle["metrics"] == whatif_model.metrics and bundle["dataset_version"] == 3
    again = run_scenario(bundle["model"], "price", 5)
    assert again.units_change_pct == run_scenario(whatif_model, "price", 5).units_change_pct
    assert load_model(storage, "ds1", 4, "whatif") is None
