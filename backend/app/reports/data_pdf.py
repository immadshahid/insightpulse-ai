"""Data report for general (non-sales) datasets: the full EDA as a branded A4 PDF."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    PageBreak,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.eda.explore import Exploration
from app.eda.predict import Prediction
from app.reports.pdf import (
    BODY,
    CARD_LABEL,
    CELL,
    CELL_BOLD,
    CHART_H,
    CONTENT_W,
    H1,
    H2,
    INDIGO,
    MARGIN,
    SMALL,
    SURFACE,
    _callout,
    _chart,
    _grid,
    _key_values,
    _p,
    draw_cover,
    draw_footer,
)

MAX_COLUMN_ROWS = 40


def _headline(ex: Exploration, prediction: Prediction | None) -> str:
    o = ex.overview
    text = (
        f"{o['rows']:,} rows and {o['columns']} columns: {o['numeric_columns']} numeric, "
        f"{o['category_columns']} categories, {o['date_columns']} dates and "
        f"{o['text_columns']} text. {o['complete_rows_pct']:.0f}% of rows are complete."
    )
    if ex.insights:
        text += f" Top finding: {ex.insights[0].headline.rstrip('.')}."
    if prediction is not None:
        text += f" {prediction.verdict}"
    return text


def _insight_card(tag: str, headline: str, why: str) -> Table:
    card = Table(
        [[_p(tag.upper(), CARD_LABEL)], [_p(headline, CELL_BOLD)], [_p(why, CELL)]],
        colWidths=[CONTENT_W],
    )
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("LINEBEFORE", (0, 0), (0, -1), 3, INDIGO),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    return card


def _stats_text(stats: list[tuple[str, str]], top: list[tuple[str, int, float]]) -> str:
    if stats:
        return ",  ".join(f"{k} {v}" for k, v in stats[:4])
    return ",  ".join(f"{v} ({s:.0f}%)" for v, _, s in top[:3])


def render_data_pdf(
    ex: Exploration,
    *,
    dataset_name: str,
    filename: str,
    cleaning: dict[str, Any] | None = None,
    prediction: Prediction | None = None,
) -> bytes:
    """The finished data report as bytes."""
    buf = io.BytesIO()
    generated = datetime.now(UTC).strftime("%d %b %Y")
    band_h = 5.2 * cm
    footer_text = f"InsightPulse AI  ·  {dataset_name}  ·  Data report"

    def first_page(canvas, doc) -> None:
        draw_cover(
            canvas,
            band_h,
            "INSIGHTPULSE AI  ·  DATA REPORT",
            dataset_name,
            f"{filename}  ·  {ex.overview['rows']:,} rows",
            f"Generated {generated}",
        )
        draw_footer(canvas, doc, footer_text)

    def footer(canvas, doc) -> None:
        draw_footer(canvas, doc, footer_text)

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.9 * cm,
        title=f"InsightPulse data report - {dataset_name}",
        author="InsightPulse AI",
    )
    o, cleaning = ex.overview, cleaning or {}
    story: list = [Spacer(1, band_h - MARGIN + 0.3 * cm)]
    story += [_p("At a glance", H1), _callout(_headline(ex, prediction)), Spacer(1, 10)]

    overview = [
        ("Rows", f"{o['rows']:,}"),
        ("Columns", str(o["columns"])),
        ("Numeric columns", str(o["numeric_columns"])),
        ("Category columns", str(o["category_columns"])),
        ("Missing cells", f"{o['missing_cells_pct']:.1f}%"),
        ("Complete rows", f"{o['complete_rows_pct']:.1f}%"),
        ("Duplicate rows (kept)", f"{o['duplicate_rows']:,}"),
        ("Empty rows removed", f"{int(cleaning.get('empty_rows_dropped', 0)):,}"),
    ]
    if ex.target:
        overview.append(("Outcome column", ex.target))
    if ex.quality:
        overview.append(("Data quality", f"{ex.quality['score']}/100 ({ex.quality['label']})"))
    story += [_p("Data overview (EDA)", H2), _key_values(overview), Spacer(1, 8)]
    issues = [i["message"] for i in (ex.quality or {}).get("issues", [])]
    if issues:
        story.append(_p("What the quality check noticed", H2))
        story += [_p(f"•  {issue}", BODY) for issue in issues]

    if prediction is not None:
        rows = [["#", "Column", "Influence"]] + [
            [str(i + 1), _p(name, CELL), f"{share * 100:.0f}%"]
            for i, (name, share) in enumerate(prediction.features[:10])
        ]
        story += [
            CondPageBreak(8 * cm),
            _p(f"What drives {prediction.target}", H1),
            _callout(prediction.verdict),
            Spacer(1, 6),
            _grid(rows, [1.0 * cm, CONTENT_W - 4.0 * cm, 3.0 * cm]),
            _p(
                f"{prediction.metric_name}: {prediction.score:.3f} versus "
                f"{prediction.baseline:.3f} "
                f"for a simple guess, from 5-fold cross-validation on "
                f"{prediction.rows_used:,} rows.",
                SMALL,
            ),
        ]

    if ex.charts:
        story += [PageBreak(), _p("Charts", H1)]
    for chart in ex.charts:
        story.append(CondPageBreak(CHART_H + 2.4 * cm))
        story.append(
            KeepTogether(
                [
                    _p(chart.title, H2),
                    _p(chart.caption, SMALL),
                    Spacer(1, 4),
                    _chart(chart.spec.kind, chart.spec.payload),
                    Spacer(1, 10),
                ]
            )
        )

    if ex.insights:
        story += [PageBreak(), _p("Findings", H1)]
        for ins in ex.insights:
            story += [KeepTogether([_insight_card(ins.tag, ins.headline, ins.why_it_matters)])]
            story.append(Spacer(1, 6))

    table = [["Column", "Type", "Missing", "Distinct", "Summary"]] + [
        [
            _p(c.name, CELL),
            c.kind,
            f"{c.missing_pct:.0f}%",
            f"{c.unique:,}",
            _p(_stats_text(c.stats, c.top_values), CELL),
        ]
        for c in ex.columns[:MAX_COLUMN_ROWS]
    ]
    story += [
        CondPageBreak(6 * cm),
        _p("Every column", H1),
        _grid(table, [4.0 * cm, 2.2 * cm, 1.8 * cm, 2.0 * cm, CONTENT_W - 10.0 * cm]),
    ]
    if len(ex.columns) > MAX_COLUMN_ROWS:
        story.append(_p(f"+ {len(ex.columns) - MAX_COLUMN_ROWS} more columns", SMALL))
    story += [
        Spacer(1, 14),
        _p(
            "All figures are calculated from your uploaded data. Relationships show "
            "association, not cause.",
            SMALL,
        ),
    ]
    doc.build(story, onFirstPage=first_page, onLaterPages=footer)
    return buf.getvalue()
