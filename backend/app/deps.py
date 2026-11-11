"""FastAPI dependencies: settings, storage, auth, current user, owned dataset."""

from __future__ import annotations

from functools import lru_cache

from fastapi import BackgroundTasks, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.jobs import BackgroundTasksRunner, JobRunner
from app.core.security import AuthError, AuthProvider, LocalJWTAuth
from app.core.storage import LocalStorage, Storage
from app.db import get_db
from app.models import Dataset, User

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_storage() -> Storage:
    """Storage backend (local disk; swap for S3 here later)."""
    return LocalStorage(get_settings().storage_dir)


@lru_cache
def get_auth() -> AuthProvider:
    """Auth backend (local JWT; swap for Firebase here later)."""
    return LocalJWTAuth(get_settings())


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    auth: AuthProvider = Depends(get_auth),
) -> User:
    """Resolve the bearer token to a user, or 401."""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        user_id = auth.user_id_from_token(creds.credentials)
    except AuthError:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


def get_owned_dataset(
    dataset_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dataset:
    """Load a dataset that belongs to the current user; 404 otherwise (no existence leak)."""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    return dataset


def require_ready(dataset: Dataset = Depends(get_owned_dataset)) -> Dataset:
    """A dataset whose mapping is confirmed and clean data exists."""
    if dataset.status != "ready" or not dataset.clean_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This dataset needs its column mapping confirmed first."
        )
    return dataset


def get_job_runner(background_tasks: BackgroundTasks) -> JobRunner:
    """Job runner (FastAPI BackgroundTasks now; swap for a Celery runner here later)."""
    return BackgroundTasksRunner(background_tasks)
