"""Tiny thread-safe LRU cache for per-process memoisation (frames, insights)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable


class LRU[V]:
    """Bounded mapping that evicts the least recently used entry."""

    def __init__(self, maxsize: int = 32) -> None:
        self.maxsize = maxsize
        self._data: OrderedDict[Hashable, V] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_set(self, key: Hashable, factory: Callable[[], V]) -> V:
        """Return the cached value for ``key`` or compute, store and return it."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        value = factory()
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
        return value

    def clear(self) -> None:
        """Drop everything."""
        with self._lock:
            self._data.clear()
