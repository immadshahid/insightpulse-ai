"""Lay out a :class:`MonthlyReport` as a branded A4 PDF (ReportLab + the app's charts)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.insights.base import fmt_money
from app.reports.monthly import MonthlyReport
from app.viz.charts import render_chart

INDIGO = colors.HexColor("#4F46E5")
VIOLET = colors.HexColor("#7C3AED")
INK = colors.HexColor("#1F1F2E")
MUTED = colors.HexColor("#6B6B80")
SURFACE = colors.HexColor("#F6F6FA")
BORDER = colors.HexColor("#E4E4EE")
UP = colors.HexColor("#0F7B4F")
DOWN = colors.HexColor("#B42318")
SOFT = colors.HexColor("#EEF0FF")

PAGE_W, PAGE_H = A4
MARGIN = 1.6 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
CHART_W = CONTENT_W
CHART_H = CHART_W * 3.4 / 6.0  # the chart renderer's aspect ratio


def _register_fonts() -> tuple[str, str]:
    """Use DejaVu Sans (shipped with matplotlib) for full Unicode; fall back to Helvetica."""
    folder = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    try:
        if "IP-Sans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("IP-Sans", str(folder / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("IP-Bold", str(folder / "DejaVuSans-Bold.ttf")))
        return "IP-Sans", "IP-Bold"
    except Exception:  # missing font files: the built-in fonts still work
        return "Helvetica", "Helvetica-Bold"


SANS, BOLD = _register_fonts()


def _style(name: str, **kw) -> ParagraphStyle:
    base = {"fontName": SANS, "fontSize": 10, "leading": 14, "textColor": INK, "alignment": TA_LEFT}
    return ParagraphStyle(name, **{**base, **kw})


H1 = _style("h1", fontName=BOLD, fontSize=15, leading=19, spaceBefore=6, spaceAfter=6)
H2 = _style("h2", fontName=BOLD, fontSize=12, leading=16, spaceBefore=4, spaceAfter=2)
BODY = _style("body")
LEAD = _style("lead", fontSize=11.5, leading=17)
SMALL = _style("small", fontSize=8.5, leading=12, textColor=MUTED)
CARD_LABEL = _style("card_label", fontSize=8.5, leading=11, textColor=MUTED)
CARD_VALUE = _style("card_value", fontName=BOLD, fontSize=16, leading=20)
CELL = _style("cell", fontSize=9, leading=12)
CELL_BOLD = _style("cell_bold", fontName=BOLD, fontSize=9, leading=12)


def _p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(text), style)


def _change(value: float | None, label: str) -> str:
    if value is None:
        return f'<font color="#6B6B80">no data {label}</font>'
    color = "#0F7B4F" if value >= 0 else "#B42318"
    arrow = "▲" if value >= 0 else "▼"
    shown = f'<font color="{color}">{arrow} {abs(value):.1f}%</font>'
    return f'{shown} <font color="#6B6B80">{label}</font>'


def _kpi_cards(report: MonthlyReport) -> Table:
    cards = []
    for k in report.kpis:
        cards.append(
            [
                _p(k.label.upper(), CARD_LABEL),
                _p(k.display, CARD_VALUE),
                Paragraph(_change(k.vs_prev, "vs last month"), SMALL),
                Paragraph(_change(k.vs_year, "vs last year"), SMALL),
            ]
        )
    per_row = 3
    rows = [cards[i : i + per_row] for i in range(0, len(cards), per_row)]
    rows[-1] += [""] * (per_row - len(rows[-1]))
    width = CONTENT_W / per_row
    table = Table(rows, colWidths=[width] * per_row)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell != "":
                style += [
                    ("BACKGROUND", (c, r), (c, r), SURFACE),
                    ("LINEBEFORE", (c, r), (c, r), 3, INDIGO),
                    ("BOX", (c, r), (c, r), 0.5, BORDER),
                ]
    table.setStyle(TableStyle(style))
    return table


def _grid(rows: list[list], widths: list[float], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), SANS),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), SOFT),
            ("FONTNAME", (0, 0), (-1, 0), BOLD),
            ("TEXTCOLOR", (0, 0), (-1, 0), INDIGO),
        ]
    table.setStyle(TableStyle(style))
    return table


def _key_values(pairs: list[tuple[str, str]], columns: int = 2) -> Table:
    cells = [[_p(k, CARD_LABEL), _p(v, CELL_BOLD)] for k, v in pairs]
    rows = []
    for i in range(0, len(cells), columns):
        row = []
        for pair in cells[i : i + columns]:
            row += pair
        row += ["", ""] * (columns - len(cells[i : i + columns]))
        rows.append(row)
    w = CONTENT_W / columns
    table = Table(rows, colWidths=[w * 0.55, w * 0.45] * columns)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _chart(kind: str, payload: dict) -> Image:
    png = render_chart(kind, payload, "light")
    return Image(io.BytesIO(png), width=CHART_W, height=CHART_H)


def _callout(text: str) -> Table:
    table = Table([[_p(text, LEAD)]], colWidths=[CONTENT_W])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("LINEBEFORE", (0, 0), (0, -1), 4, VIOLET),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def render_pdf(report: MonthlyReport) -> bytes:
    """The finished PDF as bytes."""
    buf = io.BytesIO()
    generated = datetime.now(UTC).strftime("%d %b %Y")
    band_h = 5.2 * cm

    def first_page(canvas, doc) -> None:
        canvas.saveState()
        steps = 40  # horizontal indigo-to-violet gradient band
        for i in range(steps):
            t = i / (steps - 1)
            canvas.setFillColorRGB(
                INDIGO.red + (VIOLET.red - INDIGO.red) * t,
                INDIGO.green + (VIOLET.green - INDIGO.green) * t,
                INDIGO.blue + (VIOLET.blue - INDIGO.blue) * t,
            )
            canvas.rect(PAGE_W * i / steps, PAGE_H - band_h, PAGE_W / steps + 1, band_h, 0, 1)
        canvas.setFillColorRGB(1, 1, 1, alpha=0.08)
        canvas.circle(PAGE_W - 2.2 * cm, PAGE_H - 1.0 * cm, 3.2 * cm, 0, 1)
        canvas.setFillColor(colors.white)
        canvas.setFont(SANS, 10)
        canvas.drawString(MARGIN, PAGE_H - 1.6 * cm, "INSIGHTPULSE AI  ·  MONTHLY REPORT")
        canvas.setFont(BOLD, 26)
        canvas.drawString(MARGIN, PAGE_H - 2.9 * cm, report.month_label)
        canvas.setFont(SANS, 11)
        canvas.drawString(
            MARGIN,
            PAGE_H - 3.8 * cm,
            f"{report.dataset_name}  ·  {report.first_day} to {report.last_day}",
        )
        canvas.setFont(SANS, 8.5)
        canvas.drawString(MARGIN, PAGE_H - 4.5 * cm, f"Generated {generated}")
        canvas.restoreState()
        footer(canvas, doc)

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(BORDER)
        canvas.line(MARGIN, 1.3 * cm, PAGE_W - MARGIN, 1.3 * cm)
        canvas.setFont(SANS, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            MARGIN, 0.85 * cm, f"InsightPulse AI  ·  {report.dataset_name}  ·  {report.month_label}"
        )
        canvas.drawRightString(PAGE_W - MARGIN, 0.85 * cm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.9 * cm,
        title=f"InsightPulse monthly report - {report.month_label}",
        author="InsightPulse AI",
    )
    story: list = [Spacer(1, band_h - MARGIN + 0.3 * cm)]

    story += [_p("At a glance", H1), _callout(report.headline), Spacer(1, 10)]
    story += [_kpi_cards(report), Spacer(1, 12)]
    if report.customers:
        story += [
            _p("Customers", H2),
            _key_values(list(report.customers.items())),
            Spacer(1, 6),
        ]

    story.append(CondPageBreak(CHART_H + 3.5 * cm))
    story.append(_p("How the month went", H1))
    for chart in report.charts:
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

    if report.rankings:
        story += [CondPageBreak(7 * cm), _p("Leaders this month", H1)]
        for title, rows in report.rankings.items():
            table = [["#", title.replace("Top ", "").capitalize(), "Revenue", "Share"]] + [
                [str(i + 1), _p(label, CELL), value, share]
                for i, (label, value, share) in enumerate(rows)
            ]
            story += [
                KeepTogether(
                    [
                        _p(title, H2),
                        _grid(table, [1.0 * cm, CONTENT_W - 6.2 * cm, 3.4 * cm, 1.8 * cm]),
                    ]
                ),
                Spacer(1, 10),
            ]

    story += [PageBreak(), _p("Data overview (EDA)", H1)]
    eda = report.eda
    overview = [
        ("Rows in the file", f"{eda['rows']:,}"),
        ("Rows used after cleaning", f"{eda['rows_used']:,}"),
        ("Columns", str(eda["columns"])),
        ("Date range", eda["date_range"]),
        ("History", f"{eda['history_days']:,} days"),
        ("Duplicates removed", f"{eda['duplicates_removed']:,}"),
        ("Rows dropped (no date or amount)", f"{eda['rows_dropped']:,}"),
    ]
    if eda.get("quality_score") is not None:
        overview.append(("Data quality", f"{eda['quality_score']}/100 ({eda['quality_label']})"))
    story += [_key_values(overview), Spacer(1, 10)]
    if eda.get("issues"):
        story.append(_p("What the quality check noticed", H2))
        story += [_p(f"•  {issue}", BODY) for issue in eda["issues"]]
        story.append(Spacer(1, 8))
    story += [
        _p(f"Order values in {report.month_label}", H2),
        _key_values(report.revenue_stats),
        Spacer(1, 10),
    ]
    if eda.get("column_table"):
        table = [["Column", "Type", "Missing", "Distinct values"]] + [
            [_p(name, CELL), kind, missing, distinct]
            for name, kind, missing, distinct in eda["column_table"]
        ]
        story += [
            CondPageBreak(6 * cm),
            _p("Columns in your file", H2),
            _grid(table, [CONTENT_W - 9.4 * cm, 3.4 * cm, 2.6 * cm, 3.4 * cm]),
        ]
        if eda.get("columns_not_listed"):
            story.append(_p(f"+ {eda['columns_not_listed']} more columns", SMALL))

    if report.insights or report.actions:
        story += [PageBreak(), _p("Findings and next steps", H1)]
    if report.insights:
        story.append(_p("What stands out across all your data", H2))
        for insight in report.insights:
            card = Table(
                [[_p(insight.tag.upper(), CARD_LABEL)], [_p(insight.headline, CELL_BOLD)]]
                + [[_p(insight.why_it_matters, CELL)]],
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
            story += [KeepTogether([card]), Spacer(1, 6)]
    if report.actions:
        story += [Spacer(1, 4), _p("Recommended actions", H2)]
        for i, action in enumerate(report.actions, 1):
            story += [
                KeepTogether(
                    [
                        _p(f"{i}.  {action['title']}", CELL_BOLD),
                        _p(action["detail"], CELL),
                        Spacer(1, 6),
                    ]
                )
            ]

    if report.forecast:
        f = report.forecast
        cur = report.currency
        days = f.get("horizon_days", 90)
        text = (
            f"Revenue over the next {days} days is forecast at {fmt_money(f['total'], cur)}, "
            f"likely between {fmt_money(f['total_lower'], cur)} and "
            f"{fmt_money(f['total_upper'], cur)}. {f.get('accuracy_note', '')}".strip()
        )
        story += [CondPageBreak(CHART_H + 4 * cm), _p("Looking ahead", H1), _callout(text)]
        if report.forecast_chart:
            story += [
                Spacer(1, 6),
                _chart(report.forecast_chart.kind, report.forecast_chart.payload),
            ]

    story += [
        Spacer(1, 14),
        _p(
            "All figures are calculated from your uploaded data. Forecasts are estimates "
            "with a likely range, not guarantees.",
            SMALL,
        ),
    ]
    doc.build(story, onFirstPage=first_page, onLaterPages=footer)
    return buf.getvalue()
