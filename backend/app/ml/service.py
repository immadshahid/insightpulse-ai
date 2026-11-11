"""Train-once-per-data-version access to ML models (memory -> joblib store -> train)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.lru import LRU
from app.core.storage import Storage
from app.ml.store import load_model, save_model
from app.models import Dataset

_bundles: LRU[dict[str, Any]] = LRU(maxsize=32)


def get_or_train(
    storage: Storage, dataset: Dataset, name: str, train: Callable[[], tuple[Any, dict[str, Any]]]
) -> dict[str, Any]:
    """Return ``{"model", "metrics"}`` for this dataset version, training only if needed.

    ``train`` returns ``(model, metrics)``; both are saved with joblib so a restart (or
    another worker) reuses them.
    """

    def load_or_train() -> dict[str, Any]:
        bundle = load_model(storage, dataset.id, dataset.version, name)
        if bundle is not None:
            return bundle
        model, metrics = train()
        save_model(storage, dataset.id, dataset.version, name, model, metrics)
        return {"model": model, "metrics": metrics}

    return _bundles.get_or_set((dataset.id, dataset.version, name), load_or_train)
