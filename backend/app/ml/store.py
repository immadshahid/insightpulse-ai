"""Persist trained models with joblib, together with their metrics."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import joblib

from app.core.storage import Storage
from app.insights.base import jsonable


def model_key(dataset_id: str, version: int, name: str) -> str:
    """Storage key prefix for a model bundle."""
    return f"models/{dataset_id}/v{version}/{name}"


def save_model(
    storage: Storage, dataset_id: str, version: int, name: str, model: Any, metrics: dict[str, Any]
) -> str:
    """Save ``{model, metrics, trained_at}`` as .joblib plus a readable metrics .json."""
    key = model_key(dataset_id, version, name)
    bundle = {
        "model": model,
        "metrics": jsonable(metrics),
        "trained_at": datetime.now(UTC).isoformat(),
        "dataset_version": version,
    }
    buf = io.BytesIO()
    joblib.dump(bundle, buf, compress=3)
    storage.save_bytes(f"{key}.joblib", buf.getvalue())
    storage.save_bytes(
        f"{key}.metrics.json", json.dumps(bundle["metrics"], indent=2, default=str).encode()
    )
    return f"{key}.joblib"


def load_model(storage: Storage, dataset_id: str, version: int, name: str) -> dict | None:
    """Load a bundle saved by :func:`save_model`, or None if it does not exist."""
    key = f"{model_key(dataset_id, version, name)}.joblib"
    if not storage.exists(key):
        return None
    return joblib.load(io.BytesIO(storage.read_bytes(key)))
