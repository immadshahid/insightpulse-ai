"""Run every analysis, score, and return the best insights."""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

from app.insights.anomalies import anomalies
from app.insights.base import Category, Insight, InsightContext
from app.insights.cohorts import cohort_retention
from app.insights.correlations import correlations
from app.insights.kpi import kpi_summary
from app.insights.patterns import weekday_time_pattern
from app.insights.products import top_products
from app.insights.rfm import rfm_segments
from app.insights.trend import monthly_trend

log = logging.getLogger(__name__)

Analysis = Callable[[pd.DataFrame, InsightContext], Insight | None]

ANALYSES: list[Analysis] = [
    kpi_summary,
    monthly_trend,
    top_products,
    weekday_time_pattern,
    rfm_segments,
    anomalies,
    correlations,
    cohort_retention,
]


def generate_insights(
    df: pd.DataFrame, ctx: InsightContext, limit: int = 10, category: Category | None = None
) -> list[Insight]:
    """Run all analyses on the clean frame; return up to ``limit`` sorted by score.

    An analysis that fails or does not apply (e.g. no customer column) is skipped,
    so one bad analysis never breaks the feed.
    """
    results: list[Insight] = []
    for analysis in ANALYSES:
        try:
            insight = analysis(df, ctx)
        except Exception:  # noqa: BLE001 - isolate each analysis
            log.exception("Insight %s failed", analysis.__name__)
            continue
        if insight is not None and (category is None or insight.category == category):
            results.append(insight)
    results.sort(key=lambda i: i.score, reverse=True)
    return results[:limit]
