"""What-if on shops with more products than the model has category slots."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.whatif import MAX_PRODUCT_CODES, line_frame, run_scenario, train_whatif


def test_scenario_runs_with_thousands_of_products() -> None:
    rng = np.random.default_rng(1)
    n = 4000
    quantity = rng.integers(1, 6, n).astype(float)
    df = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 200, n), unit="D"),
            "product": [f"P{i}" for i in rng.integers(0, 1500, n)],
            "quantity": quantity,
            "revenue": quantity * rng.uniform(5, 50, n),
        }
    )
    assert line_frame(df)[0]["product_code"].max() <= MAX_PRODUCT_CODES
    result = run_scenario(train_whatif(df), "price", 10.0)
    assert result.baseline_revenue > 0
