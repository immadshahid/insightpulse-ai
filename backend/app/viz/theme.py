"""Chart themes (light / dark) and Matplotlib rc settings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ThemeName = Literal["light", "dark"]

FIG_SIZE = (6.0, 3.4)  # inches - phone-friendly 16:9-ish card
DPI = 200
FONT_DIR = Path(__file__).with_name("fonts")
BRAND_FONT = "Plus Jakarta Sans"


@dataclass(frozen=True)
class Theme:
    """Colour tokens for one appearance. Text never uses series colours."""

    name: ThemeName
    surface: str
    text: str
    muted: str
    grid: str
    brand: str
    brand_soft: str
    forecast: str
    positive: str
    negative: str
    neutral_mid: str
    categorical: tuple[str, ...]

    def sequential(self) -> LinearSegmentedColormap:
        """Single-hue magnitude ramp: near-surface -> brand."""
        return LinearSegmentedColormap.from_list(f"seq_{self.name}", [self.brand_soft, self.brand])

    def diverging(self) -> LinearSegmentedColormap:
        """Two hues with a neutral grey midpoint (negative <- 0 -> positive)."""
        return LinearSegmentedColormap.from_list(
            f"div_{self.name}", [self.negative, self.neutral_mid, self.brand]
        )


LIGHT = Theme(
    name="light",
    surface="#FFFFFF",
    text="#14142B",
    muted="#5B5B76",
    grid="#E6E6EF",
    brand="#4F46E5",
    brand_soft="#E4E2FB",
    forecast="#B45309",
    positive="#0F7B4F",
    negative="#C2410C",
    neutral_mid="#ECECF2",
    # Brand first, then the dataviz reference order (blue/violet dropped to avoid
    # clashing with indigo). Max 5 + "Other" in any categorical chart.
    categorical=("#4F46E5", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#9A9AB0"),
)

DARK = Theme(
    name="dark",
    surface="#17172B",
    text="#F2F2F8",
    muted="#A6A6C0",
    grid="#2C2C46",
    brand="#8B85F5",  # brand indigo stepped lighter for >= 3:1 on the dark surface
    brand_soft="#26264A",
    forecast="#F0A14A",
    positive="#3DBE8A",
    negative="#F07A45",
    neutral_mid="#34344F",
    categorical=("#8B85F5", "#D95926", "#199E70", "#C98500", "#D55181", "#6E6E8A"),
)


def get_theme(name: str) -> Theme:
    """Return the theme by name, defaulting to light."""
    return DARK if name == "dark" else LIGHT


@lru_cache
def font_family() -> list[str]:
    """Register bundled Plus Jakarta Sans TTFs if present; fall back to DejaVu Sans."""
    if FONT_DIR.exists():
        for ttf in FONT_DIR.glob("*.ttf"):
            font_manager.fontManager.addfont(str(ttf))
    names = {f.name for f in font_manager.fontManager.ttflist}
    return [BRAND_FONT, "DejaVu Sans"] if BRAND_FONT in names else ["DejaVu Sans"]


def rc_params(theme: Theme) -> dict[str, Any]:
    """Matplotlib rcParams for a theme: large type, recessive axes and grid."""
    return {
        "font.family": "sans-serif",
        "font.sans-serif": font_family(),
        "font.size": 17,
        "axes.labelsize": 16,
        "axes.titlesize": 18,
        "xtick.labelsize": 15,
        "ytick.labelsize": 15,
        "legend.fontsize": 15,
        "figure.facecolor": theme.surface,
        "axes.facecolor": theme.surface,
        "savefig.facecolor": theme.surface,
        "axes.edgecolor": theme.grid,
        "axes.labelcolor": theme.muted,
        "text.color": theme.text,
        "xtick.color": theme.muted,
        "ytick.color": theme.muted,
        "axes.grid": False,
        "grid.color": theme.grid,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "xtick.major.size": 0,
        "xtick.major.pad": 8,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "lines.linewidth": 2.8,
        "lines.solid_capstyle": "round",
        "axes.unicode_minus": False,
    }
