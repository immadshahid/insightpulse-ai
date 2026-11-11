"""PNG cache keyed by a hash of (chart spec, theme, renderer version)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.storage import Storage
from app.viz.charts import render_chart

RENDER_VERSION = "6"  # bump to invalidate every cached PNG after a style change


def spec_hash(kind: str, payload: dict[str, Any], theme: str = "") -> str:
    """Stable short hash of a chart spec (+ theme)."""
    blob = json.dumps(
        {"k": kind, "p": payload, "t": theme, "v": RENDER_VERSION},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


class ChartCache:
    """Render-once cache for chart PNGs, stored through the Storage interface."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def get_png(self, kind: str, payload: dict[str, Any], theme: str = "light") -> bytes:
        """Return cached PNG bytes, rendering and storing them on a miss."""
        key = f"charts/{spec_hash(kind, payload, theme)}.png"
        if self.storage.exists(key):
            return self.storage.read_bytes(key)
        png = render_chart(kind, payload, theme)
        self.storage.save_bytes(key, png)
        return png
