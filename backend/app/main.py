"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app import models  # noqa: F401  (register ORM tables)
from app.api.router import api_router
from app.config import get_settings
from app.db import Base, get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create tables automatically for SQLite dev/test DBs; Postgres uses Alembic."""
    if get_settings().database_url.startswith("sqlite"):
        Base.metadata.create_all(get_engine())
    yield


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    settings = get_settings()
    app = FastAPI(title="InsightPulse AI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe (no auth)."""
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Send people who open the bare server address to the interactive API docs."""
        return RedirectResponse(url="/docs")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """No favicon; answer 204 instead of a 404 in the logs."""
        return Response(status_code=204)

    return app


app = create_app()
