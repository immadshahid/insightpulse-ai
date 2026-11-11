"""Data-quality score (0-100) with plain-language issues."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.pipeline.cleaner import CleaningReport
from app.pipeline.mapping import ColumnMapping

Severity = Literal["info", "warning", "critical"]


class QualityIssue(BaseModel):
    """One problem found in the data, written for a non-technical reader."""

    severity: Severity
    message: str


class QualityReport(BaseModel):
    """Score out of 100, a label, and the issues behind it."""

    score: int
    label: Literal["Excellent", "Good", "Fair", "Poor"]
    issues: list[QualityIssue]


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def _rows(n: int) -> str:
    return f"{n:,} row" + ("" if n == 1 else "s")


def score_quality(report: CleaningReport, mapping: ColumnMapping) -> QualityReport:
    """Compute the quality score from the cleaning report and mapping."""
    score = 100.0
    issues: list[QualityIssue] = []

    def add(deduct: float, severity: Severity, message: str) -> None:
        nonlocal score
        score -= deduct
        issues.append(QualityIssue(severity=severity, message=message))

    n = report.rows_in
    if report.missing_date_dropped:
        p = _pct(report.missing_date_dropped, n)
        add(
            min(20, p * 4),
            "critical" if p > 5 else "warning" if p > 1 else "info",
            f"{_rows(report.missing_date_dropped)} ({p:.1f}%) had no readable date and were "
            "left out.",
        )
    if report.missing_revenue_dropped:
        p = _pct(report.missing_revenue_dropped, n)
        add(
            min(20, p * 4),
            "critical" if p > 5 else "warning" if p > 1 else "info",
            f"{_rows(report.missing_revenue_dropped)} ({p:.1f}%) had no readable revenue and "
            "were left out.",
        )
    if report.duplicates_removed:
        p = _pct(report.duplicates_removed, n)
        add(
            min(10, p * 5),
            "warning" if p > 1 else "info",
            f"{_rows(report.duplicates_removed)} were exact duplicates and were removed.",
        )

    for role, why, deduct in (
        ("customer", "customer segments and retention", 6),
        ("product", "product rankings", 6),
        ("quantity", "units sold", 2),
        ("region", "city or region breakdowns", 2),
    ):
        if getattr(mapping, role) is None:
            add(deduct, "info", f"No {role} column was found, so {why} are not available.")

    optional_missing = {
        r: p
        for r, p in report.missing_pct_by_role.items()
        if r not in ("date", "revenue") and p > 0
    }
    for role, p in optional_missing.items():
        add(
            min(5, p * 2),
            "warning" if p > 5 else "info",
            f"{p:.1f}% of rows have no {role.replace('_', ' ')} value.",
        )

    if report.history_days < 60:
        add(
            15,
            "warning",
            f"Only {report.history_days} days of history. Forecasts need at "
            "least about 60 days; trends will be rough until then.",
        )
    elif report.history_days < 180:
        add(
            5,
            "info",
            f"{report.history_days} days of history. Seasonal patterns become "
            "visible after about 6 months.",
        )
    if report.rows_out < 100:
        add(10, "warning", f"Only {_rows(report.rows_out)} could be used after cleaning.")
    if report.negative_revenue_rows:
        p = _pct(report.negative_revenue_rows, report.rows_out)
        add(
            3 if p > 1 else 0,
            "info",
            f"{_rows(report.negative_revenue_rows)} have negative revenue (likely refunds); "
            "they are included in totals.",
        )

    final = max(0, min(100, round(score)))
    label = (
        "Excellent" if final >= 90 else "Good" if final >= 75 else "Fair" if final >= 50 else "Poor"
    )
    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i.severity])
    return QualityReport(score=final, label=label, issues=issues)
