"""Dataset upload, list, profile and column mapping."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import LLMClient, get_llm
from app.ai.mapping import LLMColumnMapper
from app.config import Settings, get_settings
from app.core import datasets as svc
from app.core.sheets import SheetError, fetch_sheet
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_current_user, get_owned_dataset, get_storage
from app.models import Dataset, User
from app.pipeline.loader import UnsupportedFileError
from app.pipeline.mapping import REQUIRED_ROLES, ROLES, ColumnMapping, MappingError
from app.pipeline.profiler import DatasetProfile
from app.pipeline.quality import QualityReport
from app.schemas import DatasetOut, MappingIn, ProfileOut, SheetIn

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
