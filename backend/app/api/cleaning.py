"""Data cleaning: suggested fixes, plain-language requests, preview, and apply.

Applying a plan creates a new dataset; the one it was made from is left as it is.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.cleaning import plan_cleaning
from app.ai.client import LLMClient, LLMError, get_llm
from app.ai.mapping import LLMColumnMapper
from app.api.datasets import _profile_out
from app.core import ai_quota as quota
from app.core import datasets as svc
from app.core.cleaning import (
    MAX_STEPS,
    CleanError,
    apply_steps,
    keep_valid,
    parse_steps,
    preview_dict,
    suggestions,
)
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_current_user, get_owned_dataset, get_storage
from app.models import Dataset, User
from app.pipeline.loader import UnsupportedFileError
from app.schemas import ProfileOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/datasets", tags=["cleaning"])


class StepIO(BaseModel):
    """One cleaning operation. Fields an operation doesn't use stay null or empty."""

    op: str = Field(max_length=40)
    column: str | None = Field(default=None, max_length=300)
    columns: list[str] = Field(default=[], max_length=100)
    method: str | None = Field(default=None, max_length=20)
    value: str | None = Field(default=None, max_length=300)
    new_name: str | None = Field(default=None, max_length=120)
    values: list[str] = Field(default=[], max_length=200)
    comparison: str | None = Field(default=None, max_length=20)
    keep: bool | None = None
    case: str | None = Field(default=None, max_length=10)
    to: str | None = Field(default=None, max_length=10)


class SuggestionOut(BaseModel):
    """A fix the app found by itself."""

    label: str
    steps: list[StepIO]


class SuggestionsOut(BaseModel):
    """Suggested fixes, and whether plain-language requests are available."""

    suggestions: list[SuggestionOut]
    ai_available: bool


class PlanIn(BaseModel):
    """What the user wants changed, in their own words."""

    instruction: str = Field(min_length=2, max_length=500)


class PlanOut(BaseModel):
    """The steps the request was turned into."""

    steps: list[StepIO]
    # Set when part of the request was left out, with the reason.
    note: str | None = None
    ai_questions_left: int | None = None


class StepsIn(BaseModel):
    """A plan to preview."""

    steps: list[StepIO] = Field(min_length=1, max_length=MAX_STEPS)


class ApplyIn(StepsIn):
    """A plan to apply, and an optional name for the cleaned dataset."""

    name: str | None = Field(default=None, max_length=200)


class StepEffectOut(BaseModel):
    """One step in plain words with what it changes."""

    step: StepIO
    description: str
    effect: str
    rows_removed: int
    cells_changed: int
    columns_removed: int


class PreviewOut(BaseModel):
    """What the whole plan does to the table."""

    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    steps: list[StepEffectOut]


def _run(storage: Storage, dataset: Dataset, steps: list[dict[str, Any]]):
    """Apply steps to the dataset's uploaded table; 422 with the reason if they don't fit."""
    try:
        return apply_steps(svc.load_raw(storage, dataset), parse_steps(steps))
    except CleanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/{dataset_id}/clean/suggestions", response_model=SuggestionsOut)
def clean_suggestions(
    dataset: Dataset = Depends(get_owned_dataset),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> SuggestionsOut:
    """Fixes the app can see for itself: duplicates, empty columns, gaps, mixed spellings."""
    found = suggestions(svc.load_raw(storage, dataset))
    return SuggestionsOut(
        suggestions=[SuggestionOut(**s) for s in found], ai_available=llm.available
    )


@router.post("/{dataset_id}/clean/plan", response_model=PlanOut)
def clean_plan(
    body: PlanIn,
    dataset: Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> PlanOut:
    """Turn a plain-language request into cleaning steps (checked against the data)."""
    if not llm.available:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Typed requests need the AI service, which is off on this server. "
            "The suggested fixes still work.",
        )
    if not quota.take_question(db, dataset.user_id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"{quota.limit_message()}. The suggested fixes still work.",
        )
    df = svc.load_raw(storage, dataset)
    try:
        raw_steps, note = plan_cleaning(llm, df, body.instruction)
        steps, skipped = keep_valid(df, parse_steps(raw_steps))
        if not steps:
            raise CleanError(" ".join(skipped))
        if skipped:
            note = note or "Skipped: " + " ".join(skipped)  # the model usually explains it
    except CleanError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except LLMError as exc:
        log.warning("Cleaning plan failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The AI couldn't read that request just now. Please try again.",
        ) from exc
    return PlanOut(
        steps=[StepIO(**s.to_dict()) for s in steps],
        note=note,
        ai_questions_left=quota.questions_left(db, dataset.user_id),
    )


@router.post("/{dataset_id}/clean/preview", response_model=PreviewOut)
def clean_preview(
    body: StepsIn,
    dataset: Dataset = Depends(get_owned_dataset),
    storage: Storage = Depends(get_storage),
) -> PreviewOut:
    """What the plan would change, step by step. Nothing is saved."""
    _, preview = _run(storage, dataset, [s.model_dump() for s in body.steps])
    return PreviewOut(**preview_dict(preview))


@router.post(
    "/{dataset_id}/clean/apply", response_model=ProfileOut, status_code=status.HTTP_201_CREATED
)
def clean_apply(
    body: ApplyIn,
    dataset: Dataset = Depends(get_owned_dataset),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> ProfileOut:
    """Save the cleaned table as a new dataset; the original is kept unchanged."""
    cleaned, _ = _run(storage, dataset, [s.model_dump() for s in body.steps])
    try:
        made = svc.create_from_upload(
            db,
            storage,
            user,
            "cleaned.csv",
            cleaned.to_csv(index=False).encode(),
            name=(body.name or f"{dataset.name} (cleaned)")[:200],
            mapper=LLMColumnMapper(llm),
        )
    except UnsupportedFileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _profile_out(made)
