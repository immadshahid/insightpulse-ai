"""SQLAlchemy engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@lru_cache
def get_engine() -> Engine:
    """Create (once) the engine for ``DATABASE_URL``."""
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Session factory bound to the engine."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
