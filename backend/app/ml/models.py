"""Forecasting models with one interface: fit(daily series) -> predict(horizon).

``predict`` returns a frame indexed by future dates with ``yhat``, ``lower``, ``upper``
(80% interval), never negative.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.ml.calendar import eid_proximity, holiday_flag, pakistan_holidays

Z80 = 1.2816  # two-sided 80% normal interval
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.ERROR)


class Forecaster(Protocol):
    """A fitted-or-unfitted forecasting model."""

    name: str

    def fit(self, y: pd.Series) -> Forecaster: ...
    def predict(self, horizon: int) -> pd.DataFrame: ...
    def export(self) -> Any: ...


def _future_index(y: pd.Series, horizon: int) -> pd.DatetimeIndex:
    return pd.date_range(y.index.max() + pd.Timedelta(days=1), periods=horizon, freq="D")


def _frame(index: pd.DatetimeIndex, yhat, lower, upper) -> pd.DataFrame:
    out = pd.DataFrame({"yhat": yhat, "lower": lower, "upper": upper}, index=index)
    out = out.clip(lower=0).astype("float64")
    out["lower"] = np.minimum(out["lower"], out["yhat"])
    out["upper"] = np.maximum(out["upper"], out["yhat"])
    return out


class ProphetForecaster:
    """Prophet with weekly + (if >= 1 year) yearly seasonality and Pakistan holidays."""

    name = "prophet"

    def __init__(self) -> None:
        self.model: Any = None
        self.y: pd.Series | None = None

    def fit(self, y: pd.Series) -> ProphetForecaster:
        """Fit on a daily series."""
        from prophet import Prophet

        # Prophet resets its logger level on import, so quiet it afterwards.
        logging.getLogger("prophet").setLevel(logging.ERROR)

        hol = pakistan_holidays(y.index.min().year, y.index.max().year + 2)
        self.model = Prophet(
            interval_width=0.8,
            weekly_seasonality=True,
            yearly_seasonality=10 if len(y) >= 365 else False,
            daily_seasonality=False,
            seasonality_mode="multiplicative",
            holidays=hol,
            uncertainty_samples=300,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model.fit(pd.DataFrame({"ds": y.index, "y": y.to_numpy()}))
        self.y = y
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Forecast ``horizon`` days after the training data."""
        idx = _future_index(self.y, horizon)
        fc = self.model.predict(pd.DataFrame({"ds": idx}))
        return _frame(
            idx, fc["yhat"].to_numpy(), fc["yhat_lower"].to_numpy(), fc["yhat_upper"].to_numpy()
        )

    def export(self) -> Any:
        """Prophet's own JSON serialisation (pickling Prophet is not supported)."""
        from prophet.serialize import model_to_json

        return {"prophet_json": model_to_json(self.model)}


class SarimaForecaster:
    """SARIMA(1,1,1)(1,0,1,7) on log1p(y) so effects scale with the level."""

    name = "sarima"

    def __init__(self) -> None:
        self.result: Any = None
        self.y: pd.Series | None = None

    def fit(self, y: pd.Series) -> SarimaForecaster:
        """Fit on a daily series."""
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = SARIMAX(
                np.log1p(y.to_numpy()),
                order=(1, 1, 1),
                seasonal_order=(1, 0, 1, 7),
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            self.result = model.fit(disp=False, maxiter=100)
        self.y = y
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Forecast with an 80% interval (back-transformed)."""
        fc = self.result.get_forecast(horizon)
        ci = np.asarray(fc.conf_int(alpha=0.2))
        mean = np.asarray(fc.predicted_mean)
        return _frame(
            _future_index(self.y, horizon), np.expm1(mean), np.expm1(ci[:, 0]), np.expm1(ci[:, 1])
        )

    def export(self) -> Any:
        """Fitted statsmodels results without the training data."""
        self.result.remove_data()
        return {"sarimax_results": self.result}


class XGBoostForecaster:
    """XGBoost on calendar + lag features around a linear trend, predicted recursively.

    Trees cannot extrapolate a trend, so the model learns the residual around a straight
    line fitted to the history. The 80% band comes from in-sample residual spread and
    widens with the forecast distance.
    """

    name = "xgboost"
    LAGS = (7, 14, 28)

    def __init__(self) -> None:
        self.model: Any = None
        self.y: pd.Series | None = None
        self.coef: np.ndarray | None = None
        self.resid_sd: float = 0.0

    def _trend(self, t: np.ndarray) -> np.ndarray:
        return np.polyval(self.coef, t)

    def _features(self, dates: pd.DatetimeIndex, resid_history: list[float]) -> np.ndarray:
        doy = dates.dayofyear.to_numpy()
        n = len(resid_history)
        lags = [resid_history[n - lag] if n >= lag else 0.0 for lag in self.LAGS]
        recent7 = float(np.mean(resid_history[-7:])) if n else 0.0
        recent28 = float(np.mean(resid_history[-28:])) if n else 0.0
        return np.array(
            [
                [
                    dates.dayofweek[0],
                    dates.month[0],
                    np.sin(2 * np.pi * doy[0] / 365.25),
                    np.cos(2 * np.pi * doy[0] / 365.25),
                    self._eid.get(dates[0], 0.0),
                    self._hol.get(dates[0], 0.0),
                    *lags,
                    recent7,
                    recent28,
                ]
            ]
        )

    def fit(self, y: pd.Series) -> XGBoostForecaster:
        """Fit on a daily series."""
        import xgboost as xgb

        t = np.arange(len(y))
        self.coef = np.polyfit(t, y.to_numpy(), 1)
        resid = (y.to_numpy() - self._trend(t)).tolist()
        span = pd.date_range(y.index.min(), y.index.max() + pd.Timedelta(days=400), freq="D")
        self._eid = eid_proximity(span).to_dict()
        self._hol = holiday_flag(span).to_dict()
        rows = [self._features(y.index[i : i + 1], resid[:i])[0] for i in range(28, len(y))]
        target = resid[28:]
        self.model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=0,
        )
        self.model.fit(np.asarray(rows), np.asarray(target))
        fitted = self.model.predict(np.asarray(rows))
        self.resid_sd = float(np.std(np.asarray(target) - fitted))
        self.y, self._resid = y, resid
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Recursive forecast: each predicted day feeds the next day's lag features."""
        idx = _future_index(self.y, horizon)
        history = list(self._resid)
        n0 = len(self.y)
        preds = []
        for i, d in enumerate(idx):
            r = float(self.model.predict(self._features(pd.DatetimeIndex([d]), history))[0])
            history.append(r)
            preds.append(self._trend(np.array([n0 + i]))[0] + r)
        yhat = np.asarray(preds)
        widen = 1 + np.sqrt(np.arange(1, horizon + 1) / 30)
        half = Z80 * self.resid_sd * widen
        return _frame(idx, yhat, yhat - half, yhat + half)

    def export(self) -> Any:
        """The fitted booster plus trend coefficients."""
        return {
            "xgb_model": self.model,
            "trend_coef": self.coef.tolist(),
            "resid_sd": self.resid_sd,
        }


class TrendForecaster:
    """Straight-line trend with a residual-based band (for short histories)."""

    name = "trend"

    def __init__(self) -> None:
        self.coef: np.ndarray | None = None
        self.sd = 0.0
        self.y: pd.Series | None = None

    def fit(self, y: pd.Series) -> TrendForecaster:
        """Fit a line to the daily values."""
        t = np.arange(len(y))
        self.coef = np.polyfit(t, y.to_numpy(), 1) if len(y) > 1 else np.array([0.0, y.mean()])
        self.sd = float(np.std(y.to_numpy() - np.polyval(self.coef, t)))
        self.y = y
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Extend the line."""
        t = np.arange(len(self.y), len(self.y) + horizon)
        yhat = np.polyval(self.coef, t)
        half = Z80 * self.sd * (1 + np.sqrt(np.arange(1, horizon + 1) / 30))
        return _frame(_future_index(self.y, horizon), yhat, yhat - half, yhat + half)

    def export(self) -> Any:
        """Line coefficients."""
        return {"coef": self.coef.tolist(), "sd": self.sd}


CANDIDATES: dict[str, type] = {
    "prophet": ProphetForecaster,
    "sarima": SarimaForecaster,
    "xgboost": XGBoostForecaster,
}
