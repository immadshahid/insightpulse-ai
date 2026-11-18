"""Dataset upload, list, profile and column mapping."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import LLMClient, get_llm
from app.ai.mapping import LLMColumnMapper
from app.config import Settings, get_settings
from app.core import datasets as svc
from app.core.combine import CombineError
from app.core.combine import preview as combine_preview
from app.core.sheets import SheetError, fetch_sheet
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_current_user, get_owned_dataset, get_storage
from app.models import Dataset, User
from app.pipeline.loader import UnsupportedFileError
from app.pipeline.mapping import REQUIRED_ROLES, ROLES, ColumnMapping, MappingError
from app.pipeline.profiler import DatasetProfile
from app.pipeline.quality import QualityReport
from app.schemas import (
    CombineIn,
    CombinePreviewIn,
    CombinePreviewOut,
    DatasetOut,
    JoinPlanOut,
    MappingIn,
    ProfileOut,
    SheetIn,
    StackPlanOut,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
SAMPLE_FILE = Path(os.path.abspath(__file__)).parents[2] / "sample_data" / "sales_sample.csv"


def _profile_out(dataset: Dataset) -> ProfileOut:
    return ProfileOut(
        dataset=svc.dataset_out(dataset),
        profile=DatasetProfile.model_validate(dataset.profile),
        mapping=ColumnMapping.model_validate(dataset.mapping or {}),
        roles=list(ROLES),
        required_roles=list(REQUIRED_ROLES),
        quality=QualityReport.model_validate(dataset.quality) if dataset.quality else None,
        cleaning=dataset.cleaning,
    )


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
) -> ProfileOut:
    """Upload a CSV/Excel file; returns the profile, proposed mapping and quality.

    With AI on, columns are mapped by the LLM (it sees only column names and 5 masked
    sample rows); otherwise, or if that fails, by name/type heuristics.
    """
    try:
        data = svc.read_upload_limited(file.file, settings.max_upload_mb * 1024 * 1024)
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    try:
        dataset = svc.create_from_upload(
            db,
            storage,
            user,
            file.filename or "upload.csv",
            data,
            name=name,
            mapper=LLMColumnMapper(llm),
        )
    except UnsupportedFileError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _profile_out(dataset)


@router.post("/sample", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def load_sample(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> ProfileOut:
    """Add the built-in demo shop, so the app can be tried without a file."""
    dataset = svc.create_from_upload(
        db,
        storage,
        user,
        SAMPLE_FILE.name,
        SAMPLE_FILE.read_bytes(),
        name="Sample shop",
        mapper=LLMColumnMapper(llm),
    )
    return _profile_out(dataset)


@router.post("/import-sheet", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def import_sheet(
    body: SheetIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
) -> ProfileOut:
    """Import a Google Sheet shared by link; afterwards it behaves like an upload."""
    try:
        data = fetch_sheet(body.url, settings.max_upload_mb * 1024 * 1024)
        dataset = svc.create_from_upload(
            db,
            storage,
            user,
            "google-sheet.csv",
            data,
            name=body.name or "Google Sheet",
            mapper=LLMColumnMapper(llm),
        )
    except (SheetError, UnsupportedFileError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _profile_out(dataset)


def _owned(db: Session, user: User, dataset_ids: list[str]) -> list[Dataset]:
    """The user's datasets for these ids, in the order given; 404 if any isn't theirs."""
    if len(set(dataset_ids)) != len(dataset_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose each dataset once.")
    found = []
    for dataset_id in dataset_ids:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None or dataset.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
        found.append(dataset)
    return found


@router.post("/combine/preview", response_model=CombinePreviewOut)
def preview_combine(
    body: CombinePreviewIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> CombinePreviewOut:
    """How these datasets would be combined: stacked (same columns) or joined (shared key)."""
    try:
        result = combine_preview(svc.combine_tables(storage, _owned(db, user, body.dataset_ids)))
    except CombineError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return CombinePreviewOut(
        suggested=result["suggested"],
        stack=StackPlanOut(**asdict(result["stack"])),
        join=JoinPlanOut(**asdict(result["join"])),
    )


@router.post("/combine", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def combine_datasets(
    body: CombineIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> ProfileOut:
    """Create a new dataset from two or more: ``stack`` files with the same columns, or
    ``join`` related files on their shared key. The originals are kept."""
    try:
        dataset = svc.create_combined(
            db,
            storage,
            user,
            _owned(db, user, body.dataset_ids),
            body.mode,
            name=body.name,
            mapper=LLMColumnMapper(llm),
        )
    except (CombineError, UnsupportedFileError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _profile_out(dataset)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset: Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> None:
    """Permanently delete a dataset and everything derived from it."""
    svc.delete_dataset(db, storage, dataset)


@router.get("", response_model=list[DatasetOut])
def list_datasets(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[DatasetOut]:
    """The current user's datasets, newest first."""
    rows = db.scalars(
        select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())
    )
    return [svc.dataset_out(d) for d in rows]


@router.get("/{dataset_id}/profile", response_model=ProfileOut)
def get_profile(dataset: Dataset = Depends(get_owned_dataset)) -> ProfileOut:
    """Column profile, current mapping, cleaning report and quality score."""
    return _profile_out(dataset)


@router.put("/{dataset_id}/mapping", response_model=ProfileOut)
def put_mapping(
    body: MappingIn,
    dataset: Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> ProfileOut:
    """Save a user-edited mapping, re-clean the data and recompute quality."""
    try:
        svc.apply_mapping(db, storage, dataset, ColumnMapping(**body.model_dump()))
    except MappingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _profile_out(dataset)
