"""GET /charts/{chart_id}.png?theme=light|dark"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.storage import Storage
from app.db import get_db
from app.deps import get_current_user, get_storage
from app.models import Chart, User
from app.viz.cache import ChartCache, spec_hash
from app.viz.charts import ChartError

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get(
    "/{chart_id}.png", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
def get_chart_png(
    chart_id: str,
    request: Request,
    theme: Literal["light", "dark"] = Query("light"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Render (or serve from cache) a chart PNG owned by the current user."""
    chart = db.get(Chart, chart_id)
    if chart is None or chart.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chart not found")
    etag = f'"{spec_hash(chart.kind, chart.payload, theme)}"'
    # Always revalidate (the ETag makes that a cheap 304) so style changes show up at once.
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    try:
        png = ChartCache(storage).get_png(chart.kind, chart.payload, theme)
    except ChartError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return Response(content=png, media_type="image/png", headers=headers)
