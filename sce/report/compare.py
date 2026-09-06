"""The comparison sheet: candidate sites benchmarked side by side.

Two rules govern this sheet, and both are refusals.

Identical scale across every site. A figure-ground drawn to fit its own frame
is a picture of a place; drawn at the same scale as its neighbours it becomes a
measurement, and the difference in grain between two cities is legible without
reading a single number.

No composite score. It would be easy to weight these metrics and print a
ranking, and it would be worth less than the refusal. The weights encode what a
particular client values on a particular project, and inventing them here would
hide that judgement inside a number nobody can argue with. The table normalises
so the columns are comparable, and stops.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402

from .. import __version__  # noqa: E402
from ..aoi import AOI  # noqa: E402
from . import figures as F  # noqa: E402
from . import style as S  # noqa: E402
from .sheet import _git_sha  # noqa: E402

Bundle = Sequence[tuple[AOI, dict[str, Any], dict[str, Any]]]

# label, metric group, key, format, unit, higher_is_better
# `higher_is_better` is None where the question has no good answer in general:
# a steeper site is not worse, it is different, and the bar is drawn without a
# direction so nobody reads a preference into it.
ROWS: list[tuple[str, str, str, str, str, bool | None]] = [
    ("Intersection density", "street", "intersection_density_km2", "{:.0f}", "/km²", None),
    ("Street length density", "street", "street_length_density_km_km2", "{:.1f}", "km/km²", None),
    ("Mean segment length", "street", "segment_length_mean_m", "{:.0f}", "m", None),
    ("Dead-end share", "street", "dead_end_share", "{:.1%}", "", None),
    ("Orientation order φ", "street", "orientation_order_phi", "{:.2f}", "", None),
    ("Ground space index", "fabric", "gsi", "{:.2f}", "", None),
    ("Floor space index", "fabric", "fsi", "{:.2f}", "", None),
    ("Median footprint", "fabric", "footprint_area_median_m2", "{:.0f}", "m²", None),
    ("Median block area", "fabric", "block_area_median_ha", "{:.2f}", "ha", None),
    ("10-min walk reach", "access", "walk_reach_ratio_10min", "{:.2f}", "", None),
    ("Amenity categories", "access", "amenity_category_count_10min", "{:.0f}", "", None),
    ("Nearest transport", "access", "nearest_transit_distance_m", "{:.0f}", "m", None),
    ("Mean slope", "terrain", "slope_mean_deg", "{:.1f}", "°", None),
    ("Area under 1:20", "terrain", "buildable_fraction_under_1_20", "{:.0%}", "", None),
    ("Elevation range", "terrain", "elevation_range_m", "{:.0f}", "m", None),
    ("Heating degree days", "climate", "hdd_18c", "{:.0f}", "", None),
    ("Cooling degree days", "climate", "cdd_18c", "{:.0f}", "", None),
    ("Annual GHI", "climate", "ghi_kwh_m2_year", "{:.0f}", "kWh/m²", None),
]

MAX_SITES = 4


def render_compare(path: Path | str, bundle: Bundle) -> Path:
    """Draw the comparison sheet for two to four sites."""
    S.apply()
    path = Path(path)
    sites = list(bundle)[:MAX_SITES]
    if len(sites) < 2:
        raise ValueError("compare needs at least two sites")

    n = len(sites)
    fig = plt.figure(figsize=S.A3_LANDSCAPE)
    left, right, top, bottom, wspace, hspace = 0.035, 0.965, 0.87, 0.075, 0.06, 0.10

    # The drawings are square, so the row they sit in must be exactly as tall as
    # they are wide. Deriving it rather than guessing keeps the table hard up
    # against them at two sites or at four, instead of leaving a band of white
    # whose size depends on how many sites were asked for.
    fig_w_in, fig_h_in = S.A3_LANDSCAPE
    panel_w_in = (right - left) * fig_w_in / (n + (n - 1) * wspace)
    avail_in = (top - bottom) * fig_h_in
    drawing_share = min(panel_w_in / avail_in, 0.72)
    gs = GridSpec(2, n, figure=fig, left=left, right=right, top=top, bottom=bottom,
                  height_ratios=[drawing_share, 1.0 - drawing_share],
                  wspace=wspace, hspace=hspace)

    # One scale for every site, taken from the largest AOI, so the drawings are
    # directly comparable rather than each fitted to its own frame.
    span = max(a.bounds_metric[2] - a.bounds_metric[0] for a, _, _ in sites)

    for col, (aoi, layers, _metrics) in enumerate(sites):
        ax = fig.add_subplot(gs[0, col])
        _figure_ground_at_common_scale(ax, aoi, layers, span)
        S.panel_title(ax, aoi.name, f"{aoi.epsg}  ·  {aoi.area_ha:.0f} ha")

    ax_tbl = fig.add_subplot(gs[1, :])
    _comparison_table(ax_tbl, sites, span)

    _header(fig, sites, span)
    _footer(fig, sites)

    fig.savefig(path, format=path.suffix.lstrip(".") or "pdf", facecolor=S.PAPER)
    plt.close(fig)
    return path


def _figure_ground_at_common_scale(ax, aoi: AOI, layers: dict[str, Any], span: float) -> None:
    """Draw each site centred in a window of identical ground width.

    A site with a smaller AOI is shown with white around it rather than blown up
    to fill the panel. The empty margin is honest: it says this site was analysed
    over less ground.
    """
    F.figure_ground(ax, aoi, layers)
    cx = (aoi.bounds_metric[0] + aoi.bounds_metric[2]) / 2
    cy = (aoi.bounds_metric[1] + aoi.bounds_metric[3]) / 2
    half = span / 2
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)


def _value(metrics: dict[str, Any], group: str, key: str) -> float | None:
    raw = (metrics.get(group) or {}).get(key)
    return float(raw) if isinstance(raw, (int, float)) and raw == raw else None


def _comparison_table(ax, sites: list, span: float) -> None:
    """A metric per row, a site per column, with a normalised bar behind each.

    The bar is scaled to the largest value in its own row, so it shows relative
    magnitude within a metric and never across metrics. There is no total.
    """
    S.strip(ax)
    ax.set_aspect("auto")
    ax.set_xlim(0, 1)

    n = len(sites)
    label_w = 0.22
    col_w = (1.0 - label_w) / n
    rows = [r for r in ROWS if any(_value(m, r[1], r[2]) is not None for _, _, m in sites)]
    ax.set_ylim(len(rows) + 1.6, -0.4)

    for col, (aoi, _, _) in enumerate(sites):
        x = label_w + col * col_w + col_w / 2
        ax.text(x, -0.05, " ".join(aoi.name.upper()), fontsize=S.FS["small"],
                color=S.INK, ha="center", va="baseline", weight="bold")
    ax.plot([0, 1], [0.25, 0.25], color=S.RULE, lw=S.LW["thin"], clip_on=False)

    for i, (label, group, key, spec, unit, _) in enumerate(rows):
        y = i + 1.15
        ax.text(0, y, label, fontsize=S.FS["small"], color=S.INK, va="baseline")
        if unit:
            ax.text(label_w - 0.012, y, unit, fontsize=S.FS["micro"], color=S.MUTED,
                    va="baseline", ha="right")

        values = [_value(m, group, key) for _, _, m in sites]
        present = [v for v in values if v is not None]
        peak = max((abs(v) for v in present), default=0.0)

        for col, value in enumerate(values):
            x0 = label_w + col * col_w
            if value is None:
                ax.text(x0 + col_w - 0.015, y, "—", fontsize=S.FS["small"],
                        color=S.MUTED, va="baseline", ha="right", family="monospace")
                continue
            if peak > 0:
                frac = abs(value) / peak
                ax.add_patch(plt.Rectangle((x0 + 0.004, y - 0.28), (col_w - 0.02) * frac, 0.62,
                                           facecolor=S.FAINT, edgecolor="none", zorder=0))
            ax.text(x0 + col_w - 0.015, y, spec.format(value), fontsize=S.FS["small"],
                    color=S.INK, va="baseline", ha="right", family="monospace", zorder=2)

        if i % 2 == 1:
            ax.plot([0, 1], [y + 0.42, y + 0.42], color=S.FAINT, lw=S.LW["hair"], clip_on=False)


def _header(fig, sites: list, span: float) -> None:
    fig.text(0.035, 0.955, "SITE COMPARISON", fontsize=S.FS["title"], color=S.INK,
             weight="bold", va="top")
    names = "   ·   ".join(a.name for a, _, _ in sites)
    fig.text(0.035, 0.922, names, fontsize=S.FS["small"], color=S.MUTED, va="top")
    fig.text(0.965, 0.955, f"all drawings at one scale  ·  {span / 1000:.1f} km across",
             fontsize=S.FS["small"], color=S.INK, ha="right", va="top")
    fig.text(0.965, 0.928,
             "normalised for comparison; deliberately not scored",
             fontsize=S.FS["micro"], color=S.ACCENT, ha="right", va="top")
    S.rule_line(fig, 0.908, lw=S.LW["line"])


def _footer(fig, sites: list) -> None:
    S.rule_line(fig, 0.055, lw=S.LW["thin"])
    fig.text(0.035, 0.040,
             "Bars are scaled within each row only, never across rows, and there is no total. "
             "Weighting these metrics against one another is the client's judgement, not the tool's.",
             fontsize=S.FS["micro"], color=S.MUTED, va="top")
    epsgs = "  ·  ".join(f"{a.name} {a.epsg}" for a, _, _ in sites)
    fig.text(0.035, 0.024, epsgs, fontsize=S.FS["micro"], color=S.MUTED, va="top",
             family="monospace")
    fig.text(0.965, 0.040, f"sce {__version__}  ·  {_git_sha()}",
             fontsize=S.FS["micro"], color=S.MUTED, ha="right", va="top",
             family="monospace")
