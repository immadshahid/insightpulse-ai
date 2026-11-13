"""Pydantic v2 request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.insights.base import Category
from app.insights.dashboard import KpiCard, PeriodWindow
from app.pipeline.mapping import ColumnMapping
from app.pipeline.profiler import DatasetProfile
from app.pipeline.quality import QualityReport


# ----------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    """New account credentials."""

    email: EmailStr
    # Strength rules live in core.security.password_problem (plain-language errors).
    password: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    """Login credentials."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class FirebaseLoginIn(BaseModel):
    """A Firebase ID token from Google sign-in on the device."""

    id_token: str = Field(min_length=20, max_length=8000)


class UserOut(BaseModel):
    """Public user fields."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str


class TokenOut(BaseModel):
    """Bearer token response."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


# ----------------------------------------------------------------- datasets
DatasetStatus = Literal["processing", "needs_mapping", "ready", "failed"]


class DatasetOut(BaseModel):
    """Dataset summary for lists and the dataset chip."""

    id: str
    name: str
    filename: str
    status: DatasetStatus
    kind: Literal["sales", "general"] = "sales"
    row_count: int
    version: int
    created_at: datetime
    quality_score: int | None = None
    date_min: str | None = None
    date_max: str | None = None
    currency: str | None = None


class ProfileOut(BaseModel):
    """Everything the Data screen needs: columns, AI/heuristic mapping, quality."""

    dataset: DatasetOut
    profile: DatasetProfile
    mapping: ColumnMapping
    roles: list[str]
    required_roles: list[str]
    quality: QualityReport | None = None
    cleaning: dict[str, Any] | None = None


class SheetIn(BaseModel):
    """A Google Sheets link to import."""

    url: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, max_length=200)


class MappingIn(BaseModel):
    """User-edited role mapping; null means 'no column for this role'."""

    date: str | None = None
    revenue: str | None = None
    quantity: str | None = None
    product: str | None = None
    customer: str | None = None
    region: str | None = None
    order_id: str | None = None


# ----------------------------------------------------------------- insights
class InsightOut(BaseModel):
    """An insight card as the app renders it."""

    id: str
    kind: str
    category: Category
    tag: str
    headline: str
    why_it_matters: str
    score: float
    data: dict[str, Any]
    chart_url: str | None
    narrative: str | None = None


AiStatus = Literal["off", "pending", "ready", "failed"]


class InsightsOut(BaseModel):
    """Insight feed. ``narratives`` turns 'ready' once the AI text job has finished."""

    dataset_id: str
    items: list[InsightOut]
    narratives: AiStatus = "off"


class AiSummary(BaseModel):
    """Headline summary: template text until the AI version is ready and verified."""

    text: str
    source: Literal["template", "llm"] = "template"
    status: AiStatus = "off"


class DashboardOut(BaseModel):
    """Home screen payload."""

    dataset_id: str
    period: str
    window: PeriodWindow
    currency: str | None
    kpis: list[KpiCard]
    ai_summary: AiSummary
    top_insights: list[InsightOut]
    charts: dict[str, str | None]
    forecast: ForecastStatus | None = None


# ----------------------------------------------------------------- ML (Phase 2)
class ForecastStatus(BaseModel):
    """State of the Home screen's automatic revenue forecast."""

    status: Literal["pending", "ready", "failed", "unavailable"]
    job_id: str | None = None
    model: str | None = None
    accuracy_note: str | None = None


class ForecastIn(BaseModel):
    """Forecast request."""

    target: Literal["revenue", "orders", "quantity"] = "revenue"
    horizon_days: int = Field(90, ge=7, le=365)


class JobOut(BaseModel):
    """A background job and, once finished, its result or error."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    status: Literal["queued", "running", "succeeded", "failed"]
    dataset_id: str
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ChurnIn(BaseModel):
    """Churn request; leave ``churn_days`` empty to pick the window automatically."""

    churn_days: int | None = Field(None, ge=14, le=180)


class WhatIfIn(BaseModel):
    """What-if request: % price change, or percentage-point discount change."""

    lever: Literal["price", "discount"] = "price"
    change_pct: float = Field(ge=-30, le=30)


# ----------------------------------------------------------------- AI (Phase 3)
class ChatMessage(BaseModel):
    """A previous turn, so follow-ups like 'and last month?' make sense."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatIn(BaseModel):
    """Ask-AI request."""

    message: str = Field(min_length=1, max_length=500)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


class AgentStepOut(BaseModel):
    """One thing the agents did to reach an answer."""

    agent: Literal["knowledge", "sql", "csv", "calculator"]
    summary: str
    detail: str = ""


class SourceOut(BaseModel):
    """A saved finding or definition the answer drew on."""

    title: str
    text: str


class ChatOut(BaseModel):
    """Ask-AI answer with chart, numbers and how they were computed."""

    answer: str
    chart_url: str | None
    data: dict[str, Any] | None
    follow_ups: list[str]
    how: str | None
    plan: dict[str, Any] | None
    answerable: bool
    source: Literal["llm", "template", "agent", "offline"]
    steps: list[AgentStepOut] = []
    sources: list[SourceOut] = []
    # AI questions the user can still ask today; null when there is no daily limit.
    ai_questions_left: int | None = None


class ActionOut(BaseModel):
    """One recommended action."""

    title: str
    detail: str
    impact: Literal["high", "medium", "low"]
    based_on: list[str]


class RecommendationsOut(BaseModel):
    """Top 3 actions; ``source`` is 'llm' or 'rules' (no AI configured / AI failed)."""

    dataset_id: str
    actions: list[ActionOut]
    source: Literal["llm", "rules"]


DashboardOut.model_rebuild()
