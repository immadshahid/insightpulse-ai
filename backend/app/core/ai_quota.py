"""Daily allowance of AI questions per user, so a public server has predictable AI costs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AiUsage


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def daily_limit() -> int:
    """Questions per user per UTC day; 0 means no limit."""
    return max(0, get_settings().ai_daily_questions)


def questions_left(db: Session, user_id: str) -> int | None:
    """AI questions the user can still ask today (None when there is no limit)."""
    limit = daily_limit()
    if not limit:
        return None
    row = db.get(AiUsage, (user_id, _today()))
    return max(0, limit - (row.questions if row else 0))


def take_question(db: Session, user_id: str) -> bool:
    """Use one of today's AI questions. False when the allowance is used up."""
    limit = daily_limit()
    if not limit:
        return True
    row = db.get(AiUsage, (user_id, _today()))
    if row is None:
        row = AiUsage(user_id=user_id, day=_today(), questions=0)
        db.add(row)
    if row.questions >= limit:
        return False
    row.questions += 1
    db.commit()
    return True


def limit_message() -> str:
    """Shown when the day's AI questions are used up."""
    return f"You've used today's {daily_limit()} AI questions. They reset at midnight UTC"
