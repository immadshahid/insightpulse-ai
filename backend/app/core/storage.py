"""File storage behind a small interface (local disk now, S3 later)."""

from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Protocol

import pandas as pd


class Storage(Protocol):
    """Key/value blob storage. Keys are '/'-separated relative paths."""

    def save_bytes(self, key: str, data: bytes) -> None: ...
    def read_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def delete_tree(self, prefix: str) -> None: ...


class LocalStorage:
    """Stores blobs under a root directory on local disk."""

    def __init__(self, root: str | Path) -> None:
        # abspath, not resolve(): resolve() expands a subst drive back to a path that can
        # exceed the Windows length limit.
        self.root = Path(os.path.abspath(root))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = Path(os.path.abspath(self.root / key))
        if self.root not in path.parents:
            raise ValueError(f"Invalid storage key: {key}")
        return path

    def save_bytes(self, key: str, data: bytes) -> None:
        """Write atomically (temp file + rename)."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def read_bytes(self, key: str) -> bytes:
        """Read a blob; raises FileNotFoundError if missing."""
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        """True if the key exists."""
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        """Delete a blob if present."""
        self._path(key).unlink(missing_ok=True)

    def delete_tree(self, prefix: str) -> None:
        """Delete everything stored under a key prefix."""
        shutil.rmtree(self._path(prefix), ignore_errors=True)


def save_parquet(storage: Storage, key: str, df: pd.DataFrame) -> None:
    """Serialise a DataFrame to Parquet and store it."""
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    storage.save_bytes(key, buf.getvalue())


def load_parquet(storage: Storage, key: str) -> pd.DataFrame:
    """Load a stored Parquet DataFrame."""
    return pd.read_parquet(io.BytesIO(storage.read_bytes(key)))
