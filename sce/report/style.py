"""The visual language of the sheet.

It is the web app's drawing sheet on paper: white sheet, black ink, graphite for
anything secondary, and one red line that only ever marks the site. One typeface,
Archivo, with its expanded cut for the site name and the key figures, as on screen.
The colours are the web app's (web/app/globals.css, web/lib/layers.ts), so a sheet
printed from a site reads like the panel it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
from matplotlib import font_manager

from ..vocab import LANDUSE as _LANDUSE
from ..vocab import colours as _vocab_colours

# A3 landscape in inches. Vector PDF, so this is the real printed size.
A3_LANDSCAPE = (16.54, 11.69)

# Static cuts of Archivo (SIL OFL), built by scripts/build_sheet_fonts.py.
FONT_DIR = Path(__file__).parent / "fonts"
FONT = "Archivo"
FONT_WIDE = "Archivo Expanded"

INK = "#000000"
PAPER = "#ffffff"
MUTED = "#6b7069"  # the web app's graphite
RULE = "#dadcd7"
FAINT = "#ecedea"
RED_LINE = "#e0261b"  # the site, and nothing else
ACCENT = RED_LINE
BUILT = INK
CONTEXT = "#c3c5bf"
WATER = "#a9c3d0"
GREEN = "#c3cfad"
ROAD = MUTED
CONTOUR = "#92400e"
CONTOUR_LABEL = "#78350f"

# Sun path arcs and wind bands, as in the web app's climate panel.
SUN = {"21 Jun": "#b45309", "21 Mar / 23 Sep": "#6d5fa6", "21 Dec": "#1d4ed8"}
WIND = ("#d5d7d2", "#b0b3ad", "#8a8e87", "#5f635d", "#34372f", "#000000")

# From sce/vocab.py so the sheet, SVG, QML and web agree on class names.
LANDUSE_COLOURS = {**_vocab_colours(_LANDUSE, sheet=True), "unmapped": "#f2f2ef"}

# The ESA WorldCover palette deliberately lives with its provider
# (sce.providers.landcover_worldcover.CLASS_COLOURS) and not here, so the raster
# panel and the land-use bar cannot drift apart. sce.report.figures reads it.

# Statutory designations, by planning.data.gov.uk dataset: the web map's colours and labels.
# Dash patterns as well, so the sheet survives a black-and-white print, which is how a
# planning pack usually arrives.
CONSTRAINT_STYLES = {
    "conservation-area": ("Conservation area", "#15803d", (0, (4, 2))),
    "listed-building": ("Listed building", "#9a3412", (0, (1.5, 1.5))),
    "listed-building-outline": ("Listed building outline", "#9a3412", (0, (1.5, 1.5))),
    "flood-risk-zone": ("Flood risk zone", "#1d4ed8", (0, (6, 2, 1, 2))),
    "article-4-direction-area": ("Article 4 direction area", "#a16207", (0, (3, 1, 1, 1))),
}
CONSTRAINT_OTHER = ("Other constraint", "#7e22ce", (0, (2, 2)))
# Kept for callers that cycle by index.
CONSTRAINT_COLOURS = tuple(c for _, c, _ in CONSTRAINT_STYLES.values())
CONSTRAINT_DASHES = tuple(d for _, _, d in CONSTRAINT_STYLES.values())

# Four weights, used consistently: hairline, line, emphasis, frame.
LW = {"hair": 0.25, "thin": 0.4, "line": 0.7, "bold": 1.2}

FS = {"micro": 6.0, "small": 7.0, "body": 7.5, "label": 8.5, "head": 11.0, "figure": 15.0, "title": 24.0}


@dataclass(frozen=True)
class SheetStyle:
    ink: str = INK
    paper: str = PAPER
    rule: str = RULE
    accent: str = ACCENT
    muted: str = MUTED


def _register_fonts() -> list[str]:
    """Add the bundled Archivo cuts to matplotlib; the families found, else []."""
    families = []
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_manager.fontManager.addfont(str(path))
        families.append(font_manager.FontProperties(fname=str(path)).get_name())
    return families


def apply() -> None:
    """Set the global matplotlib style. Called once before any figure is made."""
    _register_fonts()
    mpl.rcParams.update(
        {
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            # A list, so glyphs Archivo lacks (φ) fall back to DejaVu Sans, which matplotlib ships.
            "font.family": [FONT, "DejaVu Sans"],
            "font.sans-serif": [FONT, "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
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
            "legend.fontsize": FS["micro"],
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
    for spine in ax.spines.values():
        spine.set_visible(keep_frame)
        if keep_frame:
            spine.set_linewidth(LW["thin"])
            spine.set_color(RULE)
    ax.set_aspect("equal")


def panel_title(ax, text: str, sub: str = "", *, pad: float = 6.0) -> None:
    """A section heading above the panel, as the web app's cards have: sentence case,
    semibold, with an optional graphite note on the right. No rule: space separates.

    Offsets are in points, not axes fractions: a fraction of a tall panel is a
    much larger gap than a fraction of a short one, which makes every title sit
    at a different height. Polar panels pass a larger `pad` to clear their N label.
    """
    ax.set_title("")
    ax.annotate(
        text[:1].upper() + text[1:],
        xy=(0, 1),
        xycoords="axes fraction",
        xytext=(0, pad),
        textcoords="offset points",
        fontsize=FS["label"],
        color=INK,
        ha="left",
        va="bottom",
        weight="semibold",
        annotation_clip=False,
    )
    if sub:
        ax.annotate(
            sub,
            xy=(1, 1),
            xycoords="axes fraction",
            xytext=(0, pad),
            textcoords="offset points",
            fontsize=FS["micro"],
            color=MUTED,
            ha="right",
            va="bottom",
            annotation_clip=False,
        )


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
    ax.add_patch(
        mpl.patches.Rectangle((bx, by), half, h, facecolor=INK, edgecolor=INK, lw=LW["hair"], zorder=20)
    )
    ax.add_patch(
        mpl.patches.Rectangle(
            (bx + half, by), half, h, facecolor=PAPER, edgecolor=INK, lw=LW["hair"], zorder=20
        )
    )
    label = f"{length:.0f} m" if length < 1000 else f"{length / 1000:.0f} km"
    backing = dict(facecolor=PAPER, edgecolor="none", pad=0.8)
    ax.text(bx, by + h * 1.8, "0", fontsize=FS["micro"], ha="center", va="bottom", zorder=20, bbox=backing)
    ax.text(
        bx + length,
        by + h * 1.8,
        label,
        fontsize=FS["micro"],
        ha="center",
        va="bottom",
        zorder=20,
        bbox=backing,
    )


def north_arrow(ax, *, x: float = 0.955, y: float = 0.06) -> None:
    """North is grid north in the sheet's metric CRS, which is what the drawing is in."""
    ax.annotate(
        "",
        xy=(x, y + 0.055),
        xytext=(x, y),
        xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-|>", color=INK, lw=LW["line"], shrinkA=0, shrinkB=0),
        zorder=20,
    )
    ax.text(
        x,
        y + 0.062,
        "N",
        transform=ax.transAxes,
        fontsize=FS["small"],
        color=INK,
        ha="center",
        va="bottom",
        weight="semibold",
        zorder=20,
        bbox=dict(facecolor=PAPER, edgecolor="none", pad=0.8),
    )


def rule_line(
    fig, y: float, x0: float = 0.03, x1: float = 0.97, lw: float | None = None, color: str = RULE
) -> None:
    fig.add_artist(mpl.lines.Line2D([x0, x1], [y, y], color=color, lw=lw or LW["thin"]))
