"""AI endpoints: Ask-AI chat and recommended actions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.agents.service import answer_with_agents
from app.ai.agents.workspace import Ledger
from app.ai.chat import ChatAnswer, ChatTurn, ask
from app.ai.client import LLMClient, LLMError, get_llm
from app.ai.offline import answer_offline
from app.ai.recommendations import recommend
from app.config import get_settings
from app.core import ai_quota as quota
from app.core import datasets as svc
from app.core.jobs import latest_job
from app.core.lru import LRU
from app.core.storage import Storage
from app.db import get_db
from app.deps import get_storage, require_ready, require_sales
from app.models import Dataset
from app.schemas import (
    ActionOut,
    AgentStepOut,
    ChatIn,
    ChatOut,
    RecommendationsOut,
    SourceOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/datasets", tags=["ai"])
_recs: LRU[RecommendationsOut] = LRU(maxsize=64)
HOME_FORECAST = {"target": "revenue", "horizon_days": 90}


@router.post("/{dataset_id}/chat", response_model=ChatOut)
def chat(
    body: ChatIn,
    dataset: Dataset = Depends(require_ready),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> ChatOut:
    """Answer a question about the dataset with numbers computed by pandas."""
    history = [ChatTurn(role=m.role, content=m.content) for m in body.history]
    # Each question that uses the AI service counts towards the user's daily allowance.
    over_limit = llm.available and not quota.take_question(db, dataset.user_id)
    if dataset.kind == "general":
        result, ledger = _general_chat(llm, db, storage, dataset, body.message, history, over_limit)
        return _chat_out(db, dataset, result, ledger)
    df = svc.load_clean(storage, dataset)
    currency = svc.context_for(dataset, df).currency
    result, ledger = None, None

    def offline() -> ChatAnswer:
        insights = svc.dataset_insights(storage, dataset)
        return answer_offline(df, body.message, currency, insights)

    if over_limit:
        result = offline()
        result.answer = (
            f"{quota.limit_message()}, so this is a quick answer from built-in rules.\n\n"
            f"{result.answer}"
        )
    elif not llm.available:
        result = offline()
    elif get_settings().agentic_chat and hasattr(llm, "agent_turn"):
        try:
            result, ledger = answer_with_agents(
                llm, db, storage, dataset, body.message, currency, history
            )
        except LLMError as exc:
            log.warning("Agent team could not answer, using query plans: %s", exc)
    if result is None:
        try:
            result = ask(llm, df, body.message, currency, history)
        except LLMError as exc:
            log.warning("AI service failed, answering with rules: %s", exc)
            result = offline()
    return _chat_out(db, dataset, result, ledger)


def _general_chat(
    llm: LLMClient,
    db: Session,
    storage: Storage,
    dataset: Dataset,
    message: str,
    history: list[ChatTurn],
    over_limit: bool = False,
) -> tuple[ChatAnswer, Ledger | None]:
    """General data is answered by the agent team; without AI, point to Explore instead."""
    if over_limit:
        note = quota.limit_message()
    elif llm.available and hasattr(llm, "agent_turn"):
        try:
            return answer_with_agents(llm, db, storage, dataset, message, None, history)
        except LLMError as exc:
            log.warning("Agent team could not answer general data: %s", exc)
            note = "The AI couldn't finish this question just now. Please try again"
    else:
        note = "Ask AI needs the AI service, which is turned off on this server"
    return (
        ChatAnswer(
            answer=f"{note}. Meanwhile, the Explore view on Home shows every column's "
            "statistics, the main findings and what drives your outcome column.",
            how=None,
            follow_ups=[],
            plan=None,
            result=None,
            chart=None,
            source="offline",
            answerable=False,
        ),
        None,
    )


def _chat_out(db: Session, dataset: Dataset, result: ChatAnswer, ledger: Ledger | None) -> ChatOut:
    chart_url = svc.register_chart(db, dataset, result.chart)
    db.commit()
    return ChatOut(
        steps=[AgentStepOut(**s) for s in ledger.steps] if ledger else [],
        sources=[SourceOut(**s) for s in ledger.sources] if ledger else [],
        answer=result.answer,
        chart_url=chart_url,
        data=result.result.model_dump() if result.result else (result.extra or None),
        follow_ups=result.follow_ups,
        how=result.how,
        plan=result.plan,
        answerable=result.answerable,
        source=result.source,
        ai_questions_left=quota.questions_left(db, dataset.user_id),
    )


@router.get("/{dataset_id}/recommendations", response_model=RecommendationsOut)
def recommendations(
    dataset: Dataset = Depends(require_sales),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    llm: LLMClient = Depends(get_llm),
) -> RecommendationsOut:
    """Top 3 actions from the insights (and the revenue forecast once it is ready)."""
    forecast_job = latest_job(db, dataset, "forecast", HOME_FORECAST)
    forecast_ready = bool(forecast_job and forecast_job.status == "succeeded")

    def compute() -> RecommendationsOut:
        df = svc.load_clean(storage, dataset)
        currency = svc.context_for(dataset, df).currency
        extras = {}
        if forecast_ready and forecast_job.result:
            r = forecast_job.result
            extras["revenue_forecast_next_90_days"] = {
                k: r.get(k)
                for k in ("total", "total_lower", "total_upper", "change_pct", "accuracy_note")
            }
        actions, source = recommend(llm, svc.dataset_insights(storage, dataset), currency, extras)
        return RecommendationsOut(
            dataset_id=dataset.id,
            source=source,
            actions=[ActionOut(**a.model_dump()) for a in actions],
        )

    key = (dataset.id, dataset.version, llm.model, forecast_ready)
    return _recs.get_or_set(key, compute)
