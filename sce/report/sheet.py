"""The A3 sheet.

One page per site, figure-ground dominant. The layout is fixed: a reader who has
seen one sheet can find the same number in the same place on the next one, which
is the whole point of a standard drawing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

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


def render_sheet(
    path: Path | str,
    aoi: AOI,
    layers: dict[str, Any],
    metrics: dict[str, Any],
    assessment: dict[str, Any] | list[str] | None = None,
) -> Path:
    """Draw and write the sheet. Vector PDF unless the suffix says otherwise."""
    S.apply()
    path = Path(path)
    fig = plt.figure(figsize=S.A3_LANDSCAPE)

    # Left two thirds is the figure-ground; the right third is the analytical
    # column. Nothing competes with the drawing for the eye.
    gs = GridSpec(
        6,
        12,
        figure=fig,
        left=0.035,
        right=0.965,
        top=0.895,
        bottom=0.075,
        wspace=0.55,
        hspace=0.75,
    )

    ax_fg = fig.add_subplot(gs[0:4, 0:7])
    F.figure_ground(ax_fg, aoi, layers)
    S.panel_title(ax_fg, "figure ground", f"{aoi.area_ha:.0f} ha  ·  {aoi.epsg}")

    ax_terr = fig.add_subplot(gs[4:6, 0:4])
    F.terrain_hillshade(ax_terr, aoi, layers)
    S.panel_title(ax_terr, "terrain", _terrain_sub(metrics))

    ax_lc = fig.add_subplot(gs[4:6, 4:7])
    F.landcover(ax_lc, aoi, layers)
    S.panel_title(ax_lc, "land cover", "ESA WorldCover 10 m")

    ax_rose = fig.add_subplot(gs[0:2, 7:9], projection="polar")
    F.orientation_rose(ax_rose, metrics)
    S.panel_title(ax_rose, "street orientation")

    ax_wind = fig.add_subplot(gs[2:4, 7:9], projection="polar")
    F.wind_rose(ax_wind, layers)
    S.panel_title(ax_wind, "wind")

    ax_sun = fig.add_subplot(gs[0:2, 9:12])
    F.sun_path(ax_sun, aoi)
    S.panel_title(ax_sun, "sun path", f"{aoi.centroid_lonlat[1]:.2f}° lat")

    ax_lu = fig.add_subplot(gs[2:3, 9:12])
    F.landuse_bars(ax_lu, metrics)
    S.panel_title(ax_lu, "land use")

    ax_tbl = fig.add_subplot(gs[3:6, 9:12])
    _metrics_table(ax_tbl, metrics)
    S.panel_title(ax_tbl, "metrics")

    ax_loc = fig.add_subplot(gs[4:6, 7:9])
    F.locator(ax_loc, aoi)
    S.panel_title(ax_loc, "location")

    _header(fig, aoi)
    _title_block(fig, aoi, layers, _warnings_of(assessment))

    fig.savefig(path, format=path.suffix.lstrip(".") or "pdf", bbox_inches=None, facecolor=S.PAPER)
    plt.close(fig)
    return path


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
    """Set with ax.text, not ax.table.

    ax.table produces a spreadsheet. A sectioned list set on a baseline grid
    produces a drawing's schedule, which is what this is.
    """
    S.strip(ax)
    ax.set_aspect("auto")
    ax.set_xlim(0, 1)
    rows = metric_rows(metrics)
    height = sum(1.5 if r.note else 1.0 for r in rows)
    ax.set_ylim(height, 0)

    cursor = 0.0
    for row in rows:
        i = cursor
        y = i + 0.72
        cursor += 1.5 if row.note else 1.0
        if row.is_section:
            ax.text(
                0,
                y,
                " ".join(row.label.upper()),
                fontsize=S.FS["micro"],
                color=S.MUTED,
                weight="bold",
                va="baseline",
            )
            ax.plot([0, 1], [i + 0.92, i + 0.92], color=S.FAINT, lw=S.LW["hair"], clip_on=False)
            continue
        ax.text(0, y, row.label, fontsize=S.FS["small"], color=S.INK, va="baseline")
        ax.text(
            1,
            y,
            row.value,
            fontsize=S.FS["small"],
            color=S.INK,
            va="baseline",
            ha="right",
            family="monospace",
        )
        if row.note:
            ax.text(0, y + 0.42, row.note, fontsize=S.FS["micro"], color=S.MUTED, va="baseline", ha="left")


def _header(fig, aoi: AOI) -> None:
    lon, lat = aoi.centroid_lonlat
    fig.text(0.035, 0.955, aoi.name.upper(), fontsize=S.FS["title"], color=S.INK, weight="bold", va="top")
    fig.text(0.035, 0.925, "SITE CONTEXT REPORT", fontsize=S.FS["small"], color=S.MUTED, va="top")
    fig.text(
        0.965,
        0.955,
        f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}   {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}",
        fontsize=S.FS["label"],
        color=S.INK,
        ha="right",
        va="top",
        family="monospace",
    )
    fig.text(
        0.965,
        0.928,
        f"{aoi.epsg}   ·   {aoi.area_ha:.0f} ha   ·   r = {aoi.radius_m:.0f} m" if aoi.radius_m else aoi.epsg,
        fontsize=S.FS["small"],
        color=S.MUTED,
        ha="right",
        va="top",
    )
    S.rule_line(fig, 0.912, lw=S.LW["line"])


def _title_block(fig, aoi: AOI, layers: dict[str, Any], warnings: list[str] | None) -> None:
    """Coordinates, EPSG, sources with retrieval dates, licences, version, SHA.

    A drawing without a title block is a picture. This is the block a GIS
    specialist reads first and the reason the sheet can be trusted.
    """
    S.rule_line(fig, 0.055, lw=S.LW["thin"])

    seen: dict[str, Any] = {}
    non_commercial: list[str] = []
    for result in layers.values():
        for src in getattr(result, "sources", []):
            seen.setdefault(src.name, src)
            if not getattr(src, "commercial_ok", True):
                non_commercial.append(src.name)

    lines = [f"{src.name} ({src.licence}, retrieved {src.retrieved[:10]})" for src in list(seen.values())[:4]]
    if lines:
        fig.text(
            0.035,
            0.042,
            "SOURCES   " + "   ·   ".join(lines),
            fontsize=S.FS["micro"],
            color=S.MUTED,
            va="top",
            wrap=False,
        )

    if warnings:
        fig.text(
            0.035,
            0.026,
            "NOTES   " + "   ·   ".join(warnings[:3]),
            fontsize=S.FS["micro"],
            color=S.ACCENT,
            va="top",
        )

    if non_commercial:
        fig.text(
            0.035,
            0.010,
            "NON-COMMERCIAL LICENCE IN USE: " + ", ".join(sorted(set(non_commercial))),
            fontsize=S.FS["micro"],
            color=S.ACCENT,
            va="top",
            weight="bold",
        )

    fig.text(
        0.965,
        0.026,
        f"sce {__version__}  ·  {_git_sha()}  ·  {aoi.epsg}",
        fontsize=S.FS["micro"],
        color=S.MUTED,
        ha="right",
        va="top",
        family="monospace",
    )
