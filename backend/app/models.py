"""ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType


def new_id() -> str:
    """Random 32-char hex id."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


class User(Base):
    """An account. Auth is local email/password for now (see core.security)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Dataset(Base):
    """An uploaded table plus its profile, mapping, cleaning report and quality."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_key: Mapped[str] = mapped_column(String(255))
    clean_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    cleaning: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="datasets")


class Job(Base):
    """A background job (forecast training etc.). Runner: BackgroundTasks now, Celery later."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    dataset_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]] = mapped_column(JSONType)
    params_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Chart(Base):
    """A chart spec registered for a dataset; rendered on request per theme."""

    __tablename__ = "charts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
