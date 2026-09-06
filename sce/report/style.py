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

# The ESA WorldCover palette deliberately lives with its provider
# (sce.providers.landcover_worldcover.CLASS_COLOURS) and not here, so the raster
# panel and the land-use bar cannot drift apart. sce.report.figures reads it.

# Four weights, used consistently: hairline, line, emphasis, frame.
# Statutory designations. Distinguished by dash pattern as well as hue so the
# sheet survives being printed in black and white, which is how a planning pack
# usually arrives.
CONSTRAINT_COLOURS = (ACCENT, "#4a6b8a", "#7a5c86", "#2f6b52")
CONSTRAINT_DASHES = ((0, (4, 2)), (0, (1.5, 1.5)), (0, (6, 2, 1, 2)), (0, (3, 1, 1, 1)))

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
    """A rule and a label above the panel.

    Offsets are in points, not axes fractions: a fraction of a tall panel is a
    much larger gap than a fraction of a short one, which makes every title sit
    at a different height and, on the tallest panel, collide with the header.
    """
    ax.set_title("")
    ax.annotate(" ".join(text.upper()), xy=(0, 1), xycoords="axes fraction",
                xytext=(0, 9), textcoords="offset points", fontsize=FS["small"],
                color=INK, ha="left", va="bottom", weight="bold",
                annotation_clip=False)
    if sub:
        ax.annotate(sub, xy=(1, 1), xycoords="axes fraction",
                    xytext=(0, 9), textcoords="offset points", fontsize=FS["micro"],
                    color=MUTED, ha="right", va="bottom", annotation_clip=False)
    ax.annotate("", xy=(0, 1), xycoords="axes fraction", xytext=(0, 6),
                textcoords="offset points", annotation_clip=False)
    line = mpl.lines.Line2D([0, 1], [1, 1], transform=ax.transAxes, color=RULE,
                            lw=LW["thin"], clip_on=False)
    line.set_transform(ax.transAxes + mpl.transforms.ScaledTranslation(
        0, 6 / 72.0, ax.figure.dpi_scale_trans))
    ax.add_line(line)


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
    Its height is fixed in points so it reads as a hairline rule at any panel
    size rather than a slab on the large ones.
    """
    length = nice_scale_length(span_m)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    bx = x0 + x * (x1 - x0)
    by = y0 + y * (y1 - y0)
    # 2.5 pt tall, converted into data units through the axes' own height so the
    # bar is the same visual weight on the large panel and the small ones.
    axes_height_in = ax.figure.get_size_inches()[1] * ax.get_position().height
    h = abs(y1 - y0) * (2.5 / 72.0) / max(axes_height_in, 1e-6)

    half = length / 2.0
    ax.add_patch(mpl.patches.Rectangle((bx, by), half, h, facecolor=INK, edgecolor=INK,
                                       lw=LW["hair"], zorder=20))
    ax.add_patch(mpl.patches.Rectangle((bx + half, by), half, h, facecolor=PAPER,
                                       edgecolor=INK, lw=LW["hair"], zorder=20))
    label = f"{length:.0f} m" if length < 1000 else f"{length / 1000:.0f} km"
    ax.text(bx, by + h * 1.8, "0", fontsize=FS["micro"], color=INK, ha="center",
            va="bottom", zorder=20)
    ax.text(bx + length, by + h * 1.8, label, fontsize=FS["micro"], color=INK,
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
