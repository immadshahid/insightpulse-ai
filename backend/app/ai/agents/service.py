"""Builds what the agents need for a dataset and runs them for the API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents.knowledge import KnowledgeBase, build_passages
from app.ai.agents.orchestrator import ask_agentic
from app.ai.agents.workspace import Ledger, Workspace, build_workspace
from app.ai.chat import ChatAnswer, ChatTurn
from app.config import get_settings
from app.core import datasets as svc
from app.core.lru import LRU
from app.core.storage import Storage
from app.models import Dataset, Job
from app.pipeline.loader import load_table

_workspaces: LRU[Workspace] = LRU(maxsize=8)


def workspace_for(storage: Storage, dataset: Dataset, currency: str | None) -> Workspace:
    """Sanitised data copies for this dataset version (memoised per process)."""

    def build() -> Workspace:
        clean = svc.load_clean(storage, dataset)
        raw = load_table(storage.read_bytes(dataset.raw_key), dataset.filename)
        return build_workspace(clean, raw, dataset.mapping or {}, currency)

    return _workspaces.get_or_set((dataset.id, dataset.version), build)


def _finished_forecasts(db: Session, dataset: Dataset) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Job)
        .where(
            Job.dataset_id == dataset.id,
            Job.dataset_version == dataset.version,
            Job.kind == "forecast",
            Job.status == "succeeded",
        )
        .order_by(Job.created_at.desc())
    ).all()
    latest: dict[str, dict[str, Any]] = {}
    for job in rows:
        latest.setdefault(job.params_key, job.result or {})
    return [r for r in latest.values() if r]


def knowledge_for(db: Session, storage: Storage, dataset: Dataset, ws: Workspace) -> KnowledgeBase:
    """Search index over this dataset's findings, forecasts and definitions."""
    passages = build_passages(
        svc.dataset_insights(storage, dataset),
        {"mapping": dataset.mapping, "quality": dataset.quality},
        _finished_forecasts(db, dataset),
        ws.pseudo,
        ws.real_customers,
    )
    return KnowledgeBase(passages)


def answer_with_agents(
    llm: Any,
    db: Session,
    storage: Storage,
    dataset: Dataset,
    question: str,
    currency: str | None,
    history: list[ChatTurn],
) -> tuple[ChatAnswer, Ledger]:
    """Run the agent team on one question."""
    ws = workspace_for(storage, dataset, currency)
    kb = knowledge_for(db, storage, dataset, ws)
    return ask_agentic(llm, ws, kb, question, history, get_settings().agent_deadline_seconds)
