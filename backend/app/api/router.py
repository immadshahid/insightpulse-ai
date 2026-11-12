"""Aggregate API router mounted at /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import ai, auth, charts, dashboard, datasets, ml, reports

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(dashboard.router)
api_router.include_router(charts.router)
api_router.include_router(ml.router)
api_router.include_router(ai.router)
api_router.include_router(reports.router)
