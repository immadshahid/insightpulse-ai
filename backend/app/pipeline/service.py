"""Pipeline orchestration: raw bytes -> profile -> mapping -> clean frame -> quality."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.pipeline.cleaner import CleaningReport, clean
from app.pipeline.loader import load_table
from app.pipeline.mapping import ColumnMapper, ColumnMapping, HeuristicMapper, validate_mapping
from app.pipeline.profiler import DatasetProfile, profile_dataframe, sample_rows
from app.pipeline.quality import QualityReport, score_quality


@dataclass
class PipelineResult:
    """Everything produced from one raw table."""

    raw: pd.DataFrame
    profile: DatasetProfile
    mapping: ColumnMapping
    clean: pd.DataFrame
    cleaning: CleaningReport
    quality: QualityReport


def run_pipeline(
    raw: pd.DataFrame,
    mapping: ColumnMapping | None = None,
    mapper: ColumnMapper | None = None,
    profile: DatasetProfile | None = None,
) -> PipelineResult:
    """Profile, map (unless a mapping is given), validate, clean and score ``raw``."""
    profile = profile or profile_dataframe(raw)
    if mapping is None:
        mapper = mapper or HeuristicMapper()
        mapping = mapper.map_columns(profile, sample_rows(raw))
    validate_mapping(mapping, profile.column_names())
    clean_df, report = clean(raw, mapping)
    quality = score_quality(report, mapping)
    return PipelineResult(
        raw=raw, profile=profile, mapping=mapping, clean=clean_df, cleaning=report, quality=quality
    )


def ingest_bytes(data: bytes, filename: str, mapper: ColumnMapper | None = None) -> PipelineResult:
    """Load an uploaded file and run the full pipeline on it."""
    return run_pipeline(load_table(data, filename), mapper=mapper)
