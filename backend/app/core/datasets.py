"""Dataset service: upload, re-mapping, cached clean frames, insights and chart registry."""

from __future__ import annotations

import io

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.lru import LRU
from app.core.storage import Storage, load_parquet, save_parquet
from app.eda.clean import clean_general
from app.eda.explore import Exploration, explore
from app.insights.base import ChartSpec, Insight, InsightContext
from app.insights.engine import generate_insights
from app.models import Chart, Dataset, Job, User, new_id
from app.pipeline.loader import file_extension, load_table
from app.pipeline.mapping import ColumnMapper, ColumnMapping, HeuristicMapper, MappingError
from app.pipeline.profiler import DatasetProfile, profile_dataframe, sample_rows
from app.pipeline.service import PipelineResult, run_pipeline
from app.schemas import DatasetOut, InsightOut
from app.viz.cache import RENDER_VERSION, spec_hash

_frames: LRU[pd.DataFrame] = LRU(maxsize=16)
_insights: LRU[list[Insight]] = LRU(maxsize=64)


def _persist_clean(storage: Storage, dataset: Dataset, result: PipelineResult) -> None:
    key = f"datasets/{dataset.id}/clean_v{dataset.version}.parquet"
    save_parquet(storage, key, result.clean)
    dataset.clean_key = key
    dataset.row_count = len(result.clean)
    dataset.mapping = result.mapping.model_dump()
    dataset.cleaning = result.cleaning.model_dump()
    dataset.quality = result.quality.model_dump()
    dataset.status = "ready"
    dataset.kind = "sales"
    dataset.error = None


def _profile_kinds(dataset: Dataset) -> dict[str, str]:
    return {str(c["name"]).strip(): c["kind"] for c in (dataset.profile or {}).get("columns", [])}


def _make_general(
    storage: Storage, dataset: Dataset, raw: pd.DataFrame, profile: DatasetProfile
) -> None:
    """Store a typed copy of any table and mark the dataset as general data."""
    df, report = clean_general(raw, profile)
    key = f"datasets/{dataset.id}/general_v{dataset.version}.parquet"
    save_parquet(storage, key, df)
    dataset.clean_key = key
    dataset.row_count = len(df)
    dataset.cleaning = report
    result = explore(df, _profile_kinds(dataset), report)
    dataset.quality = result.quality
    dataset.kind = "general"
    dataset.status = "ready"
    dataset.error = None


def create_from_upload(
    db: Session,
    storage: Storage,
    user: User,
    filename: str,
    data: bytes,
    name: str | None = None,
    mapper: ColumnMapper | None = None,
) -> Dataset:
    """Parse, profile, auto-map and clean an upload.

    Raises ``UnsupportedFileError`` for unreadable files (nothing is stored then). A file
    with date and revenue columns becomes sales data; any other table becomes general data
    (explored with EDA). The user can switch either way on the Data screen.
    """
    raw = load_table(data, filename)
    profile = profile_dataframe(raw)
    mapping = (mapper or HeuristicMapper()).map_columns(profile, sample_rows(raw))

    dataset_id = new_id()
    dataset = Dataset(
        id=dataset_id,
        user_id=user.id,
        filename=filename[:255],
        name=(name or filename.rsplit(".", 1)[0])[:200],
        raw_key=f"datasets/{dataset_id}/raw{file_extension(filename)}",
        profile=profile.model_dump(),
        mapping=mapping.model_dump(),
        row_count=len(raw),
        version=1,
    )
    storage.save_bytes(dataset.raw_key, data)
    try:
        result = run_pipeline(raw, mapping=mapping, profile=profile)
        _persist_clean(storage, dataset, result)
    except MappingError:
        _make_general(storage, dataset, raw, profile)
    db.add(dataset)
    db.commit()
    return dataset


def set_kind(db: Session, storage: Storage, dataset: Dataset, kind: str) -> Dataset:
    """Analyse the upload as sales or general data. Raises MappingError for sales data
    whose date and revenue columns haven't been chosen yet."""
    raw = load_table(storage.read_bytes(dataset.raw_key), dataset.filename)
    profile = DatasetProfile.model_validate(dataset.profile)
    if kind == "sales":
        mapping = ColumnMapping.model_validate(dataset.mapping or {})
        result = run_pipeline(raw, mapping=mapping, profile=profile)
        dataset.version += 1
        _persist_clean(storage, dataset, result)
    else:
        dataset.version += 1
        _make_general(storage, dataset, raw, profile)
    db.commit()
    return dataset


_explorations: LRU[Exploration] = LRU(maxsize=32)


def exploration(storage: Storage, dataset: Dataset, target: str | None = None) -> Exploration:
    """EDA of a general dataset (memoised per version and target)."""

    def compute() -> Exploration:
        df = load_clean(storage, dataset)
        return explore(df, _profile_kinds(dataset), dataset.cleaning or {}, target)

    return _explorations.get_or_set((dataset.id, dataset.version, target), compute)


def profile_kinds(dataset: Dataset) -> dict[str, str]:
    """Column kinds from the upload profile."""
    return _profile_kinds(dataset)


def apply_mapping(
    db: Session, storage: Storage, dataset: Dataset, mapping: ColumnMapping
) -> Dataset:
    """Re-clean the raw upload with a user-confirmed mapping and bump the version.

    Raises ``MappingError`` if the mapping is invalid.
    """
    raw = load_table(storage.read_bytes(dataset.raw_key), dataset.filename)
    profile = DatasetProfile.model_validate(dataset.profile)
    result = run_pipeline(
        raw, mapping=mapping.model_copy(update={"source": "user"}), profile=profile
    )
    dataset.version += 1
    _persist_clean(storage, dataset, result)
    db.commit()
    return dataset


def load_clean(storage: Storage, dataset: Dataset) -> pd.DataFrame:
    """Cleaned frame for the dataset's current version (memoised per process)."""
    assert dataset.clean_key, "dataset is not ready"
    key = (dataset.id, dataset.version)
    return _frames.get_or_set(key, lambda: load_parquet(storage, dataset.clean_key))


def context_for(dataset: Dataset, df: pd.DataFrame) -> InsightContext:
    """Insight context built from the stored cleaning report."""
    currency = (dataset.cleaning or {}).get("currency")
    return InsightContext.from_frame(df, currency)


def dataset_insights(storage: Storage, dataset: Dataset) -> list[Insight]:
    """All insights for the current version, best first (memoised per process)."""

    if dataset.kind == "general":
        return exploration(storage, dataset).insights

    def compute() -> list[Insight]:
        df = load_clean(storage, dataset)
        return generate_insights(df, context_for(dataset, df), limit=10)

    return _insights.get_or_set((dataset.id, dataset.version), compute)


def register_chart(db: Session, dataset: Dataset, spec: ChartSpec | None) -> str | None:
    """Store a chart spec (idempotent, content-addressed) and return its URL."""
    if spec is None:
        return None
    chart_id = spec_hash(spec.kind, {"dataset": dataset.id, "payload": spec.payload})
    if db.get(Chart, chart_id) is None:
        db.add(
            Chart(
                id=chart_id,
                dataset_id=dataset.id,
                user_id=dataset.user_id,
                kind=spec.kind,
                payload=spec.payload,
            )
        )
        db.flush()
    # The render version in the URL makes clients fetch fresh PNGs after a style change.
    return f"{get_settings().api_prefix}/charts/{chart_id}.png?v={RENDER_VERSION}"


def insight_out(db: Session, dataset: Dataset, insight: Insight) -> InsightOut:
    """API shape for an insight, with its chart registered."""
    return InsightOut(
        **insight.model_dump(exclude={"chart"}),
        chart_url=register_chart(db, dataset, insight.chart),
    )


def dataset_out(dataset: Dataset) -> DatasetOut:
    """API summary of a dataset."""
    cleaning = dataset.cleaning or {}
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        filename=dataset.filename,
        status=dataset.status,
        kind=dataset.kind or "sales",
        row_count=dataset.row_count,
        version=dataset.version,
        created_at=dataset.created_at,
        quality_score=(dataset.quality or {}).get("score"),
        date_min=cleaning.get("date_min"),
        date_max=cleaning.get("date_max"),
        currency=cleaning.get("currency"),
    )


def delete_dataset(db: Session, storage: Storage, dataset: Dataset) -> None:
    """Remove a dataset with its files, models, rendered charts, jobs and chart specs."""
    charts = db.scalars(select(Chart).where(Chart.dataset_id == dataset.id)).all()
    for chart in charts:
        for theme in ("light", "dark"):
            storage.delete(f"charts/{spec_hash(chart.kind, chart.payload, theme)}.png")
        db.delete(chart)
    db.execute(delete(Job).where(Job.dataset_id == dataset.id))
    storage.delete_tree(f"datasets/{dataset.id}")
    storage.delete_tree(f"models/{dataset.id}")
    db.delete(dataset)
    db.commit()


def read_upload_limited(stream: io.BufferedIOBase, max_bytes: int) -> bytes:
    """Read an upload, raising ValueError if it exceeds ``max_bytes``."""
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"File is larger than {max_bytes // (1024 * 1024)} MB.")
    return data
