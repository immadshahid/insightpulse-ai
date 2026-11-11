"""Matplotlib + Seaborn chart builders rendered to PNG.

Every builder draws onto a provided Axes from a JSON payload (see
``app.insights.base.ChartSpec``). :func:`render_chart` owns the figure lifecycle:
create -> draw -> save PNG -> ``plt.close(fig)``. Rendering is serialised with a
lock because pyplot / rcParams are process-global.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from app.insights.base import compact_number  # noqa: E402
from app.viz.theme import DPI, FIG_SIZE, Theme, get_theme, rc_params  # noqa: E402

_LOCK = threading.Lock()
Builder = Callable[[Axes, dict[str, Any], Theme], None]


class ChartError(ValueError):
    """Raised for an unknown chart kind or malformed payload."""


# ---------------------------------------------------------------- formatting
def _fmt(value: float, kind: str | None, currency: str | None = None) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if kind == "percent":
        return f"{value:.0f}%"
    if kind == "money":
        return compact_number(value)
    if kind == "corr":
        return f"{value:.2f}"
    return compact_number(value)


def _y_axis(ax: Axes, theme: Theme, kind: str | None) -> None:
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, kind)))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.grid(axis="y", color=theme.grid, linewidth=0.8)
    ax.set_axisbelow(True)


def _x_dates(ax: Axes) -> None:
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, show_offset=False))


# ---------------------------------------------------------------- builders
def line_chart(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Line(s) with optional confidence band, highlighted points and a 'Today' marker.

    Payload: x, x_is_date, series=[{name, y, role: actual|forecast|baseline, x?}],
    band={lower, upper, label, x?}, highlights=[{x, y}], today, y_format.
    """

    def xs(values: list[Any]) -> Any:
        return pd.to_datetime(values) if p.get("x_is_date") else values

    x = xs(p["x"])
    band = p.get("band")
    if band:
        bx = xs(band.get("x", p["x"]))
        color = theme.forecast if band.get("role") == "forecast" else theme.brand
        ax.fill_between(
            bx,
            np.asarray(band["lower"], dtype=float),  # null (no history yet) becomes a gap
            np.asarray(band["upper"], dtype=float),
            color=color,
            alpha=0.14,
            linewidth=0,
            label=band.get("label"),
        )

    for s in p["series"]:
        sx = xs(s["x"]) if "x" in s else x
        role = s.get("role", "actual")
        if role == "forecast":
            ax.plot(sx, s["y"], color=theme.forecast, linestyle=(0, (4, 2)), label=s["name"])
        elif role == "baseline":
            ax.plot(
                sx, s["y"], color=theme.muted, linewidth=1.4, linestyle=(0, (2, 2)), label=s["name"]
            )
        else:
            ax.plot(sx, s["y"], color=theme.brand, label=s["name"])
            if p.get("markers") == "points":
                ax.scatter(
                    sx,
                    s["y"],
                    s=28,
                    color=theme.brand,
                    edgecolor=theme.surface,
                    linewidth=1.5,
                    zorder=3,
                )

    highlights = p.get("highlights") or []
    if highlights:
        hx = xs([h["x"] for h in highlights])
        ax.scatter(
            hx,
            [h["y"] for h in highlights],
            s=70,
            color=theme.negative,
            edgecolor=theme.surface,
            linewidth=2,
            zorder=4,
            label="Unusual day",
        )

    if p.get("today"):
        t = xs([p["today"]])[0]
        ax.axvline(t, color=theme.muted, linewidth=1, linestyle=(0, (1, 2)))
        ax.annotate(
            "Today",
            xy=(t, 1),
            xycoords=("data", "axes fraction"),
            xytext=(4, -2),
            textcoords="offset points",
            va="top",
            color=theme.muted,
            fontsize=14.3,
        )

    if p.get("x_is_date"):
        _x_dates(ax)
    _y_axis(ax, theme, p.get("y_format"))
    ax.set_ylim(bottom=min(0, ax.get_ylim()[0]))
    labelled = [h for h in ax.get_legend_handles_labels()[1] if h]
    if len(labelled) >= 2:
        ax.legend(
            loc="lower left",
            bbox_to_anchor=(0, 1.0),
            ncols=min(3, len(labelled)),
            handlelength=1.2,
            handletextpad=0.4,
            columnspacing=1.0,
            labelcolor=theme.text,
            borderaxespad=0.2,
        )


def bar_ranking(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Ranked bars (horizontal by default) with direct value labels.

    Payload: labels, values, highlight=[idx], value_format, horizontal, keep_order.
    """
    labels, values = list(p["labels"]), [float(v) for v in p["values"]]
    highlight = set(p.get("highlight", []))
    colors = [theme.brand if i in highlight else theme.brand_soft for i in range(len(values))]
    fmt = p.get("value_format")
    if p.get("horizontal", True):
        pos = np.arange(len(values))[::-1]
        ax.barh(pos, values, height=0.68, color=colors, edgecolor=theme.surface, linewidth=2)
        ax.set_yticks(pos, [_truncate(lbl, 22) for lbl in labels], color=theme.text)
        ax.xaxis.set_visible(False)
        ax.spines["bottom"].set_visible(False)
        vmax = max(values) if values else 1
        for y, v in zip(pos, values, strict=True):
            ax.text(v + vmax * 0.015, y, _fmt(v, fmt), va="center", color=theme.text, fontsize=15)
        ax.set_xlim(0, vmax * 1.7)  # room for the value and the app's expand button
    else:
        pos = np.arange(len(values))
        ax.bar(pos, values, width=0.68, color=colors, edgecolor=theme.surface, linewidth=2)
        ax.set_xticks(pos, labels, color=theme.text)
        _y_axis(ax, theme, fmt)
        for i in highlight:
            ax.text(
                pos[i],
                values[i],
                _fmt(values[i], fmt),
                ha="center",
                va="bottom",
                color=theme.text,
                fontsize=15,
            )


def heatmap(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Sequential single-hue heatmap with 2px surface gaps. Payload: rows, cols, values."""
    data = pd.DataFrame(p["values"], index=p["rows"], columns=p["cols"], dtype=float)
    fmt = p.get("value_format")
    annot = None
    if p.get("annotate", True):
        annot = data.map(lambda v: _fmt(v, fmt) if pd.notna(v) else "")
    sns.heatmap(
        data,
        ax=ax,
        cmap=theme.sequential(),
        cbar=False,
        linewidths=2,
        linecolor=theme.surface,
        annot=annot,
        fmt="",
        mask=data.isna(),
        annot_kws={"fontsize": 13.7},
    )
    _contrast_annotations(ax, data, theme)
    ax.tick_params(axis="both", length=0, colors=theme.text)
    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.setp(ax.get_yticklabels(), rotation=0)


def corr_heatmap(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Diverging correlation matrix (lower triangle). Payload: labels, matrix."""
    data = pd.DataFrame(p["matrix"], index=p["labels"], columns=p["labels"], dtype=float)
    mask = np.triu(np.ones_like(data, dtype=bool), k=1)
    sns.heatmap(
        data,
        ax=ax,
        mask=mask,
        cmap=theme.diverging(),
        vmin=-1,
        vmax=1,
        center=0,
        annot=True,
        fmt=".2f",
        cbar=False,
        linewidths=2,
        linecolor=theme.surface,
        annot_kws={"fontsize": 14.3},
    )
    _contrast_annotations(ax, data.where(~mask), theme, diverging=True)
    ax.tick_params(axis="both", length=0, colors=theme.text)
    plt.setp(ax.get_yticklabels(), rotation=0)
    crowded = sum(len(str(label)) for label in p["labels"]) > 32
    plt.setp(
        ax.get_xticklabels(), rotation=35 if crowded else 0, ha="right" if crowded else "center"
    )


def distribution(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Histogram (default) or boxplot. Payload: values, kind, value_format, label."""
    values = pd.Series(p["values"], dtype=float).dropna()
    if p.get("kind") == "box":
        sns.boxplot(
            x=values,
            ax=ax,
            color=theme.brand_soft,
            linecolor=theme.brand,
            linewidth=1.6,
            fliersize=3,
            width=0.45,
        )
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, p.get("value_format"))))
        ax.grid(axis="x", color=theme.grid)
    else:
        sns.histplot(
            values,
            ax=ax,
            color=theme.brand,
            edgecolor=theme.surface,
            linewidth=1.5,
            bins=p.get("bins", "auto"),
            alpha=0.9,
        )
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, p.get("value_format"))))
        _y_axis(ax, theme, None)
    ax.set_xlabel(p.get("label", ""))
    ax.set_ylabel("")


def scatter_reg(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Scatter with a regression line + 95% band. Payload: x, y, x_label, y_label."""
    sns.regplot(
        x=np.asarray(p["x"], float),
        y=np.asarray(p["y"], float),
        ax=ax,
        scatter_kws={"s": 14, "alpha": 0.35, "color": theme.brand, "linewidths": 0},
        line_kws={"color": theme.forecast, "linewidth": 2.2},
    )
    ax.set_xlabel(p.get("x_label", ""))
    ax.set_ylabel(p.get("y_label", ""))
    _y_axis(ax, theme, p.get("y_format"))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, p.get("x_format"))))


def donut(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Donut with direct labels and a centre total. At most 5 slices + 'Other'."""
    labels, values = list(p["labels"]), [max(0.0, float(v)) for v in p["values"]]
    if len(values) > 6:
        order = np.argsort(values)[::-1]
        keep = order[:5]
        labels = [labels[i] for i in keep] + ["Other"]
        values = [values[i] for i in keep] + [sum(values[i] for i in order[5:])]
    total = sum(values) or 1.0
    colors = list(theme.categorical[: len(values)])
    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.36, "edgecolor": theme.surface, "linewidth": 2},
    )
    ax.set_aspect("equal")
    for side in (1, -1):
        for anchor, text_xy, text in _spaced_labels(wedges, labels, values, total, side):
            ax.annotate(
                text,
                xy=anchor,
                xytext=text_xy,
                ha="left" if side > 0 else "right",
                va="center",
                color=theme.text,
                fontsize=14.3,
                arrowprops={"arrowstyle": "-", "color": theme.grid, "linewidth": 1},
            )
    if p.get("center_value"):
        ax.text(
            0,
            0.08,
            p["center_value"],
            ha="center",
            va="center",
            color=theme.text,
            fontsize=16,
            fontweight="bold",
        )
        ax.text(
            0,
            -0.16,
            p.get("center_label", ""),
            ha="center",
            va="center",
            color=theme.muted,
            fontsize=14.3,
        )


def _spaced_labels(wedges, labels, values, total, side, min_gap=0.2):
    """Donut label positions for one side (1 = right, -1 = left), pushed apart vertically
    so labels of neighbouring small slices never overlap."""
    items = []
    for w, label, v in zip(wedges, labels, values, strict=True):
        share = v / total
        ang = np.deg2rad((w.theta2 + w.theta1) / 2)
        x, y = np.cos(ang), np.sin(ang)
        if share < 0.02 or (x >= 0) != (side > 0):
            continue
        items.append([y * 1.12, (x * 0.82, y * 0.82), x, f"{label}  {share * 100:.0f}%"])
    items.sort(key=lambda it: it[0], reverse=True)  # top to bottom
    for i in range(1, len(items)):
        if items[i - 1][0] - items[i][0] < min_gap:
            items[i][0] = items[i - 1][0] - min_gap
    return [(anchor, (side * max(abs(x) * 1.22, 0.95), ty), text) for ty, anchor, x, text in items]


def shap_importance(ax: Axes, p: dict[str, Any], theme: Theme) -> None:
    """Horizontal mean |SHAP| bars, largest first. Payload: features, values."""
    pairs = sorted(
        zip(p["features"], map(float, p["values"]), strict=True),
        key=lambda t: abs(t[1]),
        reverse=True,
    )[:10]
    bar_ranking(
        ax,
        {
            "labels": [f for f, _ in pairs],
            "values": [abs(v) for _, v in pairs],
            "highlight": [0],
            "value_format": p.get("value_format", "number"),
        },
        theme,
    )


BUILDERS: dict[str, Builder] = {
    "line": line_chart,
    "bar_ranking": bar_ranking,
    "heatmap": heatmap,
    "corr_heatmap": corr_heatmap,
    "distribution": distribution,
    "scatter_reg": scatter_reg,
    "donut": donut,
    "shap": shap_importance,
}


# ---------------------------------------------------------------- helpers
def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _contrast_annotations(
    ax: Axes, data: pd.DataFrame, theme: Theme, diverging: bool = False
) -> None:
    """Use surface-coloured text on strong cells and text colour on pale cells."""
    vals = data.to_numpy(dtype=float)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return
    lo, hi = float(finite.min()), float(finite.max())
    cells = [
        (r, c)
        for r in range(vals.shape[0])
        for c in range(vals.shape[1])
        if np.isfinite(vals[r, c])
    ]
    for text, (r, c) in zip(ax.texts, cells, strict=False):
        v = vals[r, c]
        strength = abs(v) if diverging else ((v - lo) / (hi - lo) if hi > lo else 0)
        text.set_color(theme.surface if strength > 0.55 else theme.text)


def render_chart(kind: str, payload: dict[str, Any], theme_name: str = "light") -> bytes:
    """Render a chart spec to PNG bytes at 6x3.4in / 200dpi. Always closes the figure."""
    builder = BUILDERS.get(kind)
    if builder is None:
        raise ChartError(f"Unknown chart kind '{kind}'")
    theme = get_theme(theme_name)
    with _LOCK, plt.rc_context(rc_params(theme)):
        fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI, layout="constrained")
        try:
            builder(ax, payload, theme)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=DPI, facecolor=theme.surface)
            return buf.getvalue()
        except (KeyError, TypeError, ValueError) as exc:
            raise ChartError(f"Bad payload for '{kind}': {exc}") from exc
        finally:
            plt.close(fig)
