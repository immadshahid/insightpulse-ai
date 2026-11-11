"""Load uploaded CSV / Excel files into pandas."""

from __future__ import annotations

import io
from pathlib import PurePath

import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xls"}


class UnsupportedFileError(ValueError):
    """Raised when a file cannot be read as tabular data."""


def file_extension(filename: str) -> str:
    """Return the lower-cased extension of ``filename`` (e.g. ``.csv``)."""
    return PurePath(filename).suffix.lower()


def load_table(data: bytes, filename: str) -> pd.DataFrame:
    """Parse raw file bytes into a DataFrame.

    CSV files are tried with common encodings and delimiter sniffing; Excel files
    use the first sheet. Column names are stripped of surrounding whitespace.
    """
    ext = file_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"Unsupported file type '{ext}'. Upload a CSV or Excel file.")
    if not data:
        raise UnsupportedFileError("The file is empty.")

    if ext in {".xlsx", ".xls"}:
        try:
            df = pd.read_excel(io.BytesIO(data), sheet_name=0)
        except Exception as exc:  # noqa: BLE001 - surface a clean message
            raise UnsupportedFileError(f"Could not read the Excel file: {exc}") from exc
    else:
        df = _read_csv(data)

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    if df.empty or len(df.columns) < 2:
        raise UnsupportedFileError("The file needs at least two columns and one row of data.")
    return df


def _read_csv(data: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        try:
            df = pd.read_csv(io.StringIO(text))
            if len(df.columns) == 1:  # probably not comma-separated
                df = pd.read_csv(io.StringIO(text), sep=None, engine="python")
            return df
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise UnsupportedFileError(f"Could not read the CSV file: {last_error}")
