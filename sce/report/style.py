"""The visual language of the sheet.

The output has to read as a drawing, not a plot. That difference is almost
entirely typography, weight and restraint: one typeface, four line weights, ink
on paper rather than a colour ramp, and a graphic scale bar measured in the
sheet's own metric CRS.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib as mpl

# A3 landscape in inches. Vector PDF, so this is the real printed size.
A3_LANDSCAPE = (16.54, 11.69)

INK = "#1a1a1a"
PAPER = "#ffffff"
RULE = "#c8c4bc"
FAINT = "#e8e4dc"
BUILT = "#242424"
WATER = "#a9c3d0"
GREEN = "#c3cfad"
ROAD = "#5a5a5a"
ACCENT = "#a4462d"
MUTED = "#8a8478"

LANDUSE_COLOURS = {
    "residential": "#d8cfc0",
    "commercial": "#c9b8b0",
    "retail": "#d3b7a8",
    "industrial": "#bdbdb4",
    "green": GREEN,
    "water": WATER,
    "institutional": "#cfc6d3",
    "transport": "#c4c4c4",
    "other": "#dedad2",
    "unmapped": "#f2efe9",
}

# The official ESA WorldCover palette, so the sheet matches every other
# publication using this dataset.
WORLDCOVER_COLOURS = {
    "Tree cover": "#006400",
    "Shrubland": "#ffbb22",
    "Grassland": "#ffff4c",
    "Cropland": "#f096ff",
    "Built-up": "#fa0000",
    "Bare / sparse vegetation": "#b4b4b4",
    "Snow and ice": "#f0f0f0",
    "Permanent water bodies": "#0064c8",
    "Herbaceous wetland": "#0096a0",
    "Mangroves": "#00cf75",
    "Moss and lichen": "#fae6a0",
}

# Four weights, used consistently: hairline, line, emphasis, frame.
LW = {"hair": 0.25, "thin": 0.4, "line": 0.7, "bold": 1.2}

FS = {"micro": 5.5, "small": 6.5, "body": 7.5, "label": 9.0, "head": 12.0, "title": 18.0}


@dataclass(frozen=True)
class SheetStyle:
    ink: str = INK
    paper: str = PAPER
    rule: str = RULE
    accent: str = ACCENT
    muted: str = MUTED


def apply() -> None:
    """Set the global matplotlib style. Called once before any figure is made."""
    mpl.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": FS["body"],
            "text.color": INK,
            "axes.edgecolor": RULE,
            "axes.labelcolor": INK,
            "axes.linewidth": LW["thin"],
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelsize": FS["small"],
            "ytick.labelsize": FS["small"],
            "legend.frameon": False,
            "legend.fontsize": FS["small"],
            "pdf.fonttype": 42,  # embed as TrueType so the PDF is editable text
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "axes.grid": False,
            "figure.dpi": 150,
            "savefig.dpi": 300,
        }
    )


def strip(ax, *, keep_frame: bool = False) -> None:
    """Remove the chart furniture. Most panels are drawings, not charts."""
    ax.set_xticks([])
    ax.set_yticks([])
    for side, spine in ax.spines.items():
        spine.set_visible(keep_frame)
        if keep_frame:
            spine.set_linewidth(LW["thin"])
            spine.set_color(RULE)
    ax.set_aspect("equal")


def panel_title(ax, text: str, sub: str = "") -> None:
    """A rule and a label above the panel. Consistent placement is the point."""
    ax.set_title("")
    ax.text(0, 1.035, " ".join(text.upper()), transform=ax.transAxes,
            fontsize=FS["small"], color=INK, ha="left", va="bottom", weight="bold")
    if sub:
        ax.text(1, 1.035, sub, transform=ax.transAxes, fontsize=FS["micro"],
                color=MUTED, ha="right", va="bottom")
    ax.plot([0, 1], [1.02, 1.02], transform=ax.transAxes, color=RULE,
            lw=LW["thin"], clip_on=False)


def nice_scale_length(span_m: float) -> float:
    """A round scale-bar length that sits near a quarter of the drawing width."""
    target = span_m / 4.0
    for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000):
        if step >= target:
            return float(step)
    return 10000.0


def scale_bar(ax, span_m: float, *, y: float = 0.045, x: float = 0.045) -> None:
    """A graphic scale bar drawn from the metric CRS.

    This is the detail that says drawing rather than plot: the bar is a real
    measured length in the sheet's own projection, not a decorative annotation.
    """
    length = nice_scale_length(span_m)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    ax_span = x1 - x0
    bx = x0 + x * ax_span
    by = y0 + y * (y1 - y0)
    h = 0.006 * ax_span

    half = length / 2.0
    ax.add_patch(mpl.patches.Rectangle((bx, by), half, h, facecolor=INK, edgecolor=INK,
                                       lw=LW["hair"], zorder=20))
    ax.add_patch(mpl.patches.Rectangle((bx + half, by), half, h, facecolor=PAPER,
                                       edgecolor=INK, lw=LW["hair"], zorder=20))
    label = f"{length:.0f} m" if length < 1000 else f"{length / 1000:.0f} km"
    ax.text(bx, by + h * 2.2, "0", fontsize=FS["micro"], color=INK, ha="center", va="bottom", zorder=20)
    ax.text(bx + length, by + h * 2.2, label, fontsize=FS["micro"], color=INK,
            ha="center", va="bottom", zorder=20)


def north_arrow(ax, *, x: float = 0.955, y: float = 0.06) -> None:
    """North is grid north in the sheet's metric CRS, which is what the drawing is in."""
    ax.annotate(
        "", xy=(x, y + 0.055), xytext=(x, y), xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color=INK, lw=LW["line"], shrinkA=0, shrinkB=0),
        zorder=20,
    )
    ax.text(x, y + 0.062, "N", transform=ax.transAxes, fontsize=FS["small"],
            color=INK, ha="center", va="bottom", zorder=20)


def rule_line(fig, y: float, x0: float = 0.03, x1: float = 0.97, lw: float | None = None) -> None:
    fig.add_artist(mpl.lines.Line2D([x0, x1], [y, y], color=RULE, lw=lw or LW["thin"]))
