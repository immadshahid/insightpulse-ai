"""Charts render without error, at the right size, in both themes, and are cached."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest

from app.core.storage import LocalStorage
from app.insights.engine import generate_insights
from app.viz import cache as cache_mod
from app.viz.cache import ChartCache, spec_hash
from app.viz.charts import BUILDERS, ChartError, render_chart

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
rng = np.random.default_rng(3)

SYNTHETIC = {
    "line": {
        "x": ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
        "x_is_date": True,
        "series": [
            {"name": "Actual", "y": [5, 6, 7, 6.5], "role": "actual"},
            {
                "name": "Forecast",
                "x": ["2026-04-01", "2026-05-01"],
                "y": [6.5, 7.2],
                "role": "forecast",
            },
        ],
        "band": {
            "x": ["2026-04-01", "2026-05-01"],
            "lower": [6.5, 6.4],
            "upper": [6.5, 8.0],
            "label": "80% range",
            "role": "forecast",
        },
        "today": "2026-04-01",
        "y_format": "money",
    },
    "bar_ranking": {
        "labels": ["A", "B", "C"],
        "values": [30, 20, 10],
        "highlight": [0],
        "value_format": "money",
    },
    "heatmap": {
        "rows": ["Mon", "Tue"],
        "cols": ["AM", "PM"],
        "values": [[1, 2], [3, None]],
        "value_format": "number",
    },
    "corr_heatmap": {
        "labels": ["a", "b", "c"],
        "matrix": [[1, 0.5, -0.4], [0.5, 1, 0.1], [-0.4, 0.1, 1]],
    },
    "distribution": {"values": rng.lognormal(8, 0.5, 500).tolist(), "value_format": "money"},
    "scatter_reg": {
        "x": rng.normal(0, 1, 200).tolist(),
        "y": rng.normal(0, 1, 200).tolist(),
        "x_label": "Discount",
        "y_label": "Revenue",
    },
    "donut": {
        "labels": list("ABCDEFG"),
        "values": [40, 20, 10, 8, 7, 5, 2],
        "center_value": "1.2M",
        "center_label": "Revenue",
    },
    "shap": {"features": ["price", "discount", "weekday"], "values": [0.4, -0.2, 0.05]},
}


def _png_size(png: bytes) -> tuple[int, int]:
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def test_every_builder_has_a_synthetic_case() -> None:
    assert set(SYNTHETIC) == set(BUILDERS)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("kind", sorted(SYNTHETIC))
def test_builders_render_phone_sized_png(kind: str, theme: str) -> None:
    png = render_chart(kind, SYNTHETIC[kind], theme)
    assert png.startswith(PNG_MAGIC)
    assert _png_size(png) == (1200, 680)  # 6 x 3.4 in at 200 dpi
    assert plt.get_fignums() == []  # figure was closed


def test_line_band_with_missing_history_renders() -> None:
    """Early days have no rolling band yet, stored as null in the chart spec."""
    payload = {
        "x": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "x_is_date": True,
        "series": [{"name": "Revenue", "y": [1.0, 2.0, 3.0]}],
        "band": {"lower": [None, 1.0, 1.5], "upper": [None, 3.0, 4.0]},
    }
    assert render_chart("line", payload).startswith(b"\x89PNG")


def test_box_variant_renders() -> None:
    png = render_chart("distribution", {**SYNTHETIC["distribution"], "kind": "box"}, "dark")
    assert png.startswith(PNG_MAGIC)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_insight_charts_render(clean_df, ctx, theme: str) -> None:
    charts = [i.chart for i in generate_insights(clean_df, ctx) if i.chart]
    assert len(charts) >= 4
    for chart in charts:
        assert render_chart(chart.kind, chart.payload, theme).startswith(PNG_MAGIC)


def test_unknown_or_bad_payload_raises_and_closes() -> None:
    with pytest.raises(ChartError):
        render_chart("pie3d", {})
    with pytest.raises(ChartError):
        render_chart("bar_ranking", {"labels": ["a"]})
    assert plt.get_fignums() == []


def test_cache_renders_once_per_theme(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    real = cache_mod.render_chart

    def counting(kind, payload, theme):
        calls.append(theme)
        return real(kind, payload, theme)

    monkeypatch.setattr(cache_mod, "render_chart", counting)
    cache = ChartCache(LocalStorage(tmp_path))
    p = SYNTHETIC["bar_ranking"]
    a = cache.get_png("bar_ranking", p, "light")
    b = cache.get_png("bar_ranking", p, "light")
    cache.get_png("bar_ranking", p, "dark")
    assert a == b and calls == ["light", "dark"]
    assert spec_hash("bar_ranking", p, "light") != spec_hash("bar_ranking", p, "dark")
