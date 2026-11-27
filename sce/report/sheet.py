"""The A3 sheet.

One page per site, figure-ground dominant. The layout is fixed: a reader who has
seen one sheet can find the same number in the same place on the next one, which
is the whole point of a standard drawing.
"""

from __future__ import annotations

import math
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Rectangle

from .. import __version__
from ..aoi import AOI
from . import figures as F
from . import style as S
from .tables import metric_rows


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


# Page geometry in inches (A3 landscape). Everything is placed on this grid rather than
# a GridSpec, so a panel's title, legend and neighbour can never share the same space.
W, H = S.A3_LANDSCAPE
M = 0.55  # outer margin
HEADER_RULE = H - 1.2
BODY_TOP = HEADER_RULE - 0.45  # leaves room for the first row of panel titles
BODY_BOTTOM = 1.25
FOOTER_RULE = 0.98
FG = BODY_TOP - BODY_BOTTOM  # the figure ground is square and as tall as the body
RIGHT = M + FG + 0.5  # the analytical columns start here
COL_GAP = 0.3
COL = (W - M - RIGHT - 2 * COL_GAP) / 3
COLS = tuple(RIGHT + i * (COL + COL_GAP) for i in range(3))


def _axes(fig, x: float, y: float, w: float, h: float, **kw):
    """An axes placed in inches from the bottom-left corner of the page."""
    return fig.add_axes((x / W, y / H, w / W, h / H), **kw)


def render_sheet(
    path: Path | str,
    aoi: AOI,
    layers: dict[str, Any],
    metrics: dict[str, Any],
    assessment: dict[str, Any] | list[str] | None = None,
    *,
    title: str | None = None,
) -> Path:
    """Draw and write the sheet. Vector PDF unless the suffix says otherwise."""
    path = Path(path)
    fig = build_sheet(aoi, layers, metrics, assessment, title=title)
    fig.savefig(path, format=path.suffix.lstrip(".") or "pdf", bbox_inches=None, facecolor=S.PAPER)
    plt.close(fig)
    return path


def build_sheet(
    aoi: AOI,
    layers: dict[str, Any],
    metrics: dict[str, Any],
    assessment: dict[str, Any] | list[str] | None = None,
    *,
    title: str | None = None,
) -> Figure:
    """The sheet as a matplotlib figure, not yet written (tests inspect its layout)."""
    S.apply()
    fig = plt.figure(figsize=S.A3_LANDSCAPE)

    # The figure ground takes the left of the sheet; three narrow columns on the right
    # carry the analysis. Nothing competes with the drawing for the eye.
    ax_fg = _axes(fig, M, BODY_BOTTOM, FG, FG)
    F.figure_ground(ax_fg, aoi, layers)
    S.panel_title(ax_fg, "figure ground", f"{_site_size(aoi)}  ·  {aoi.epsg}")

    # Row 1: key figures across all three columns.
    key_h = 0.5
    ax_key = _axes(fig, RIGHT, BODY_TOP - key_h, W - M - RIGHT, key_h)
    _key_figures(ax_key, metrics)

    # Row 2: three square maps and diagrams of the same square.
    row2_top = BODY_TOP - key_h - 0.5
    ax_terr = _axes(fig, COLS[0], row2_top - COL, COL, COL)
    F.terrain_hillshade(ax_terr, aoi, layers)
    S.panel_title(ax_terr, "terrain", _terrain_sub(metrics))

    ax_lc = _axes(fig, COLS[1], row2_top - COL, COL, COL)
    F.landcover(ax_lc, aoi, layers)
    S.panel_title(ax_lc, "land cover", "ESA WorldCover 10 m")

    ax_sun = _axes(fig, COLS[2], row2_top - COL, COL, COL)
    F.sun_path(ax_sun, aoi)
    S.panel_title(ax_sun, "sun path", f"{aoi.centroid_lonlat[1]:.2f}° lat")

    # Row 3: the two roses, then the schedule down the last column.
    row3_top = row2_top - COL - 0.75  # the sun path legend sits in this gap
    rose = COL * 0.9
    ax_rose = _axes(fig, COLS[0] + (COL - rose) / 2, row3_top - rose, rose, rose, projection="polar")
    F.orientation_rose(ax_rose, metrics)
    phi = (metrics.get("street") or {}).get("orientation_order_phi")
    S.panel_title(ax_rose, "street orientation", f"order φ {phi:.2f}" if phi is not None else "", pad=16)

    ax_wind = _axes(fig, COLS[1] + (COL - rose) / 2, row3_top - rose, rose, rose, projection="polar")
    F.wind_rose(ax_wind, layers)
    S.panel_title(ax_wind, "wind", "m/s, typical year", pad=16)

    ax_tbl = _axes(fig, COLS[2], BODY_BOTTOM, COL, row3_top - BODY_BOTTOM)
    _metrics_table(ax_tbl, metrics)
    S.panel_title(ax_tbl, "schedule")

    # Row 4: land use under the roses, and the locator.
    lu_top = row3_top - rose - 0.75  # the wind legend sits in this gap
    lu_w = COLS[1] + COL - COLS[0]
    ax_lu = _axes(fig, COLS[0], lu_top - 0.85, lu_w, 0.85)
    F.landuse_bars(ax_lu, metrics)
    S.panel_title(ax_lu, "land use")

    loc_h = lu_w / 2 * 0.5
    ax_loc = _axes(fig, COLS[0], BODY_BOTTOM, lu_w / 2, loc_h)
    F.locator(ax_loc, aoi)
    S.panel_title(ax_loc, "location")

    _header(fig, aoi, (title or "").strip() or aoi.name)
    _title_block(fig, aoi, layers, _warnings_of(assessment))
    return fig


def _site_size(aoi: AOI) -> str:
    """`600 m square, 36 ha`: the size the web app shows, in the words a brief uses.

    The side comes from the area, not the bounding box, which grows when the square
    is slightly rotated in its UTM zone.
    """
    side = math.sqrt(aoi.area_ha * 1e4)
    return f"{side:.0f} m square, {aoi.area_ha:.0f} ha"


# (label, metric group, key, format, unit). The figures the web panel leads with.
KEY_FIGURES = (
    ("Floor space index", "fabric", "fsi", "{:.2f}", ""),
    ("Ground space index", "fabric", "gsi", "{:.2f}", ""),
    ("Intersections", "street", "intersection_density_km2", "{:.0f}", "/km²"),
    ("Annual sun", "climate", "ghi_kwh_m2_year", "{:.0f}", "kWh/m²"),
)


def _key_figures(ax, metrics: dict[str, Any]) -> None:
    """A row of large figures in the expanded cut, as at the top of the web panel."""
    S.strip(ax)
    ax.set_aspect("auto")
    ax.set_xlim(0, len(KEY_FIGURES))
    ax.set_ylim(0, 1)
    for i, (label, group, key, spec, unit) in enumerate(KEY_FIGURES):
        value = (metrics.get(group) or {}).get(key)
        ax.text(i, 1.0, label, fontsize=S.FS["small"], color=S.MUTED, va="top")
        text = ax.text(
            i,
            0.05,
            "—" if value is None else spec.format(value),
            fontsize=S.FS["figure"],
            family=S.FONT_WIDE,
            weight="semibold",
            va="baseline",
        )
        if unit and value is not None:
            ax.annotate(
                unit,
                xy=(1, 0),
                xycoords=text,
                xytext=(2, 0),
                textcoords="offset points",
                fontsize=S.FS["small"],
                color=S.MUTED,
                va="bottom",
            )


def _warnings_of(assessment: dict[str, Any] | list[str] | None) -> list[str]:
    """Accept either the full assessment dict from `sce.coverage.assess` or a
    plain list, so a caller holding only warnings is not forced to wrap them."""
    if assessment is None:
        return []
    if isinstance(assessment, dict):
        return list(assessment.get("warnings") or [])
    return list(assessment)


def _terrain_sub(metrics: dict[str, Any]) -> str:
    t = metrics.get("terrain") or {}
    lo, hi = t.get("elevation_min_m"), t.get("elevation_max_m")
    if lo is None or hi is None:
        return ""
    # Read the model from the metric rather than hard-coding it: with --dtm
    # fabdem this panel is bare earth, and saying DSM would be a lie.
    model = t.get("terrain_model") or "DSM"
    # En dash, because this is a range and not a minus sign.
    return f"{lo:.0f}\u2013{hi:.0f} m  \u00b7  {model}"


def _metrics_table(ax, metrics: dict[str, Any]) -> None:
    """Set with ax.text, not ax.table, as the web panel sets its figures: a sentence-case
    heading per section, graphite labels, ink values aligned right.
    """
    S.strip(ax)
    ax.set_aspect("auto")
    ax.set_xlim(0, 1)
    rows = metric_rows(metrics)
    # Fixed line pitch in points, so the schedule reads the same whatever the column height.
    line_in = 0.165
    height_in = ax.get_position().height * S.A3_LANDSCAPE[1]
    ax.set_ylim(height_in / line_in, 0)

    cursor = 0.0
    for n, row in enumerate(rows):
        if row.is_section:
            cursor += 0.0 if n == 0 else 0.55
            ax.text(
                0,
                cursor + 0.72,
                row.label[:1].upper() + row.label[1:],
                fontsize=S.FS["small"],
                color=S.INK,
                weight="semibold",
                va="baseline",
            )
            cursor += 1.15
            continue
        y = cursor + 0.72
        ax.text(0, y, row.label, fontsize=S.FS["small"], color=S.MUTED, va="baseline")
        ax.text(1, y, row.value, fontsize=S.FS["small"], color=S.INK, va="baseline", ha="right")
        cursor += 1.0
        if row.note:
            ax.text(0, cursor + 0.55, row.note, fontsize=S.FS["micro"], color=S.MUTED, va="baseline")
            cursor += 0.8


def _header(fig, aoi: AOI, title: str) -> None:
    """The Quadrat mark and the site name in the expanded cut, as the web panel opens."""
    lon, lat = aoi.centroid_lonlat
    mark = 0.46
    top = H - M
    ax_mark = _axes(fig, M, top - mark, mark, mark)
    _mark(ax_mark)
    x = M + mark + 0.18
    fig.text(
        x / W,
        top / H,
        title,
        fontsize=S.FS["title"],
        family=S.FONT_WIDE,
        weight="bold",
        color=S.INK,
        va="top",
    )
    fig.text(
        x / W, (top - 0.5) / H, "Quadrat site context report", fontsize=S.FS["label"], color=S.MUTED, va="top"
    )
    fig.text(
        (W - M) / W,
        top / H,
        f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}   {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}",
        fontsize=S.FS["head"],
        family=S.FONT_WIDE,
        weight="semibold",
        color=S.INK,
        ha="right",
        va="top",
    )
    fig.text(
        (W - M) / W,
        (top - 0.3) / H,
        f"{_site_size(aoi)}   ·   {aoi.epsg}",
        fontsize=S.FS["small"],
        color=S.MUTED,
        ha="right",
        va="top",
    )
    S.rule_line(fig, HEADER_RULE / H, M / W, (W - M) / W, lw=S.LW["line"], color=S.INK)


def _mark(ax) -> None:
    """The Quadrat mark (web/components/Logo.tsx): a 3 x 3 frame of white lines on a black tile."""
    ax.set_xlim(0, 32)
    ax.set_ylim(0, 32)
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch((0, 0), 32, 32, boxstyle="round,pad=0,rounding_size=6", fc=S.INK, ec="none"))
    for p in (3, 11, 19, 27):
        ax.add_patch(Rectangle((p, 3), 2, 26, fc=S.PAPER, ec="none"))
        ax.add_patch(Rectangle((3, p), 26, 2, fc=S.PAPER, ec="none"))


def _title_block(fig, aoi: AOI, layers: dict[str, Any], warnings: list[str] | None) -> None:
    """Coordinates, EPSG, sources with retrieval dates, licences, version, SHA.

    A drawing without a title block is a picture. This is the block a GIS
    specialist reads first and the reason the sheet can be trusted.
    """
    S.rule_line(fig, FOOTER_RULE / H, M / W, (W - M) / W, lw=S.LW["thin"])

    seen: dict[str, Any] = {}
    non_commercial: list[str] = []
    for result in layers.values():
        for src in getattr(result, "sources", []):
            seen.setdefault(src.name, src)
            if not getattr(src, "commercial_ok", True):
                non_commercial.append(src.name)

    # (heading, text, colour, weight). Notes are ink, not red: red marks the site only.
    blocks: list[tuple[str, str, str, str]] = []
    lines = [f"{src.name} ({src.licence}, retrieved {src.retrieved[:10]})" for src in list(seen.values())[:4]]
    if lines:
        blocks.append(("Sources", "   ·   ".join(lines), S.MUTED, "normal"))
    if warnings:
        blocks.append(("Notes", "   ·   ".join(warnings[:3]), S.INK, "normal"))
    if non_commercial:
        blocks.append(
            (
                "Licence",
                "Non-commercial licence in use: " + ", ".join(sorted(set(non_commercial))),
                S.INK,
                "semibold",
            )
        )

    # Wrapped to the width left of the version stamp, stacked down from the rule.
    y = FOOTER_RULE - 0.14
    step = S.FS["micro"] * 1.45 / 72
    for heading, text, colour, weight in blocks:
        fig.text(M / W, y / H, heading, fontsize=S.FS["micro"], color=S.INK, weight="semibold", va="top")
        for line in textwrap.wrap(text, 230)[:2]:
            fig.text(
                (M + 0.6) / W, y / H, line, fontsize=S.FS["micro"], color=colour, weight=weight, va="top"
            )
            y -= step
        y -= step * 0.35

    fig.text(
        (W - M) / W,
        (FOOTER_RULE - 0.14) / H,
        f"sce {__version__}  ·  {_git_sha()}  ·  {aoi.epsg}",
        fontsize=S.FS["micro"],
        color=S.MUTED,
        ha="right",
        va="top",
    )
