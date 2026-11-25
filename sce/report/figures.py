"""The individual panels of the sheet.

Each function draws into an axes handed to it and returns nothing. They are kept
separate from `sheet.py` so a panel can be developed and printed on its own, and
so the compare sheet can reuse them at an identical scale across sites.
"""

from __future__ import annotations

import math
from typing import Any

import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import BoundaryNorm, LightSource, ListedColormap

from ..aoi import AOI
from . import style as S
from .sunpath import key_arcs, stereographic


def _extent(aoi: AOI) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = aoi.bounds_metric
    return minx, maxx, miny, maxy


def _frame(ax: Axes, aoi: AOI) -> None:
    minx, maxx, miny, maxy = _extent(aoi)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    S.strip(ax, keep_frame=True)


def figure_ground(ax: Axes, aoi: AOI, layers: dict[str, Any]) -> None:
    """The dominant panel. Solid built form on paper, streets as voids.

    A figure-ground is the one drawing every architect reads instantly, which is
    why it gets the largest cell and why nothing else is allowed to compete with
    it for ink.
    """
    _frame(ax, aoi)
    water = layers.get("landuse")
    if water is not None and water.gdf is not None and "class" in water.gdf.columns:
        w = water.gdf[water.gdf["class"] == "water"]
        if len(w):
            w.plot(ax=ax, facecolor=S.WATER, edgecolor="none", zorder=1)
        g = water.gdf[water.gdf["class"] == "green_space"]
        if len(g):
            g.plot(ax=ax, facecolor=S.GREEN, edgecolor="none", alpha=0.55, zorder=1)

    streets = layers.get("streets")
    if streets is not None and streets.gdf is not None and len(streets.gdf):
        streets.gdf.plot(ax=ax, color=S.RULE, linewidth=S.LW["hair"], zorder=2)

    bld = layers.get("buildings")
    if bld is not None and bld.gdf is not None and len(bld.gdf):
        bld.gdf.plot(ax=ax, facecolor=S.BUILT, edgecolor="none", zorder=3)

    constraints_overlay(ax, layers)
    S.scale_bar(ax, aoi.bounds_metric[2] - aoi.bounds_metric[0])
    S.north_arrow(ax)


def constraints_overlay(ax: Axes, layers: dict[str, Any]) -> None:
    """Statutory designations, drawn over the figure-ground where they exist.

    This is the point of the provider seam. The command is identical in London
    and in Tashkent; a Conservation Area boundary appears on one sheet and not
    the other purely because the data exists in one place and not the other.
    Drawn as outlines rather than fills so the built form stays readable
    underneath: a designation is a line on a plan, not a wash over it.
    """
    result = layers.get("constraints")
    if result is None or result.gdf is None or not len(result.gdf):
        return
    gdf = result.gdf
    column = "dataset" if "dataset" in gdf.columns else None
    datasets = sorted(gdf[column].dropna().unique()) if column else ["constraints"]

    handles = []
    for i, name in enumerate(datasets):
        subset = gdf if column is None else gdf[gdf[column] == name]
        if not len(subset):
            continue
        colour = S.CONSTRAINT_COLOURS[i % len(S.CONSTRAINT_COLOURS)]
        dashes = S.CONSTRAINT_DASHES[i % len(S.CONSTRAINT_DASHES)]
        subset.boundary.plot(ax=ax, color=colour, linewidth=S.LW["line"], linestyle=dashes, zorder=6)
        handles.append(
            mlines.Line2D(
                [], [], color=colour, lw=S.LW["line"], linestyle=dashes, label=str(name).replace("-", " ")
            )
        )
    if handles:
        ax.legend(
            handles=handles,
            loc="upper left",
            fontsize=S.FS["micro"],
            handlelength=2.2,
            borderpad=0.5,
            labelspacing=0.35,
            facecolor=S.PAPER,
            framealpha=0.85,
            frameon=True,
            edgecolor=S.RULE,
        ).set_zorder(30)


def street_network(ax: Axes, aoi: AOI, layers: dict[str, Any]) -> None:
    """Streets alone, weighted by class, so the hierarchy reads."""
    _frame(ax, aoi)
    st = layers.get("streets")
    if st is None or st.gdf is None or not len(st.gdf):
        _empty(ax, "no street data")
        return
    gdf = st.gdf
    if "highway" in gdf.columns:
        major = gdf[
            gdf["highway"].astype(str).str.contains("motorway|trunk|primary|secondary", case=False, na=False)
        ]
        minor = gdf.drop(major.index)
        minor.plot(ax=ax, color=S.ROAD, linewidth=S.LW["hair"], zorder=2)
        major.plot(ax=ax, color=S.INK, linewidth=S.LW["line"], zorder=3)
    else:
        gdf.plot(ax=ax, color=S.ROAD, linewidth=S.LW["thin"])


def terrain_hillshade(ax: Axes, aoi: AOI, layers: dict[str, Any]) -> None:
    """Hillshade with contours over it. The shading carries the form, the
    contours carry the measurement; neither alone does both."""
    _frame(ax, aoi)
    t = layers.get("terrain")
    if t is None or t.raster is None:
        _empty(ax, "no terrain data")
        return
    arr = np.asarray(t.raster["array"], dtype=float)
    nodata = t.raster.get("nodata")
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    res = t.raster.get("res", (30.0, 30.0))
    filled = np.where(np.isnan(arr), np.nanmean(arr), arr)

    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(filled, vert_exag=2.0, dx=abs(res[0]), dy=abs(res[1]))
    minx, maxx, miny, maxy = _extent(aoi)
    ax.imshow(shade, cmap="gray", extent=(minx, maxx, miny, maxy), origin="upper", alpha=0.85, zorder=1)

    rng = float(np.nanmax(arr) - np.nanmin(arr))
    interval = _contour_interval(rng)
    levels = np.arange(math.floor(np.nanmin(arr) / interval) * interval, np.nanmax(arr) + interval, interval)
    cs = ax.contour(
        filled,
        levels=levels,
        colors=S.INK,
        linewidths=S.LW["hair"],
        extent=(minx, maxx, miny, maxy),
        origin="upper",
        zorder=2,
    )
    ax.clabel(cs, cs.levels[::2], fmt="%.0f", fontsize=S.FS["micro"], colors=S.INK)
    S.scale_bar(ax, maxx - minx)


def _contour_interval(elevation_range: float) -> float:
    for step in (0.5, 1, 2, 5, 10, 25, 50, 100):
        if elevation_range / step <= 12:
            return float(step)
    return 200.0


def landcover(ax: Axes, aoi: AOI, layers: dict[str, Any]) -> None:
    """ESA WorldCover, drawn in the official palette so it matches every other
    publication using this dataset."""
    _frame(ax, aoi)
    lc = layers.get("landcover")
    if lc is None or lc.raster is None:
        _empty(ax, "no land cover data")
        return
    from ..providers.landcover_worldcover import CLASS_COLOURS, CLASSES

    arr = np.asarray(lc.raster["array"])
    codes = sorted(CLASSES)
    colours = [CLASS_COLOURS.get(c, "#dddddd") for c in codes]
    bounds = [c - 0.5 for c in codes] + [codes[-1] + 0.5]
    cmap = ListedColormap(colours)
    norm = BoundaryNorm(bounds, cmap.N)
    minx, maxx, miny, maxy = _extent(aoi)
    ax.imshow(
        arr, cmap=cmap, norm=norm, extent=(minx, maxx, miny, maxy), origin="upper", interpolation="nearest"
    )


def orientation_rose(ax: Axes, metrics: dict[str, Any]) -> None:
    """Street bearing distribution. Paired with the wind rose directly below it,
    so a reader can say 'this grid sits 40 degrees off the prevailing wind'."""
    bins = (metrics.get("street") or {}).get("orientation_bins")
    if not bins:
        _empty(ax, "no orientation data")
        return
    counts = np.asarray(bins, dtype=float)
    n = len(counts)
    width = 2 * np.pi / n
    theta = np.arange(n) * width
    counts = counts / counts.sum() if counts.sum() else counts
    ax.bar(theta, counts, width=width * 0.92, bottom=0.0, color=S.INK, edgecolor="none", align="edge")
    _polar_furniture(ax)
    phi = (metrics.get("street") or {}).get("orientation_order_phi")
    if phi is not None:
        ax.text(
            0.5,
            -0.12,
            f"order $\\varphi$ = {phi:.2f}",
            transform=ax.transAxes,
            ha="center",
            fontsize=S.FS["small"],
            color=S.MUTED,
        )


def wind_rose(ax: Axes, layers: dict[str, Any]) -> None:
    """Frequency by direction and speed band, from the ERA5 archive."""
    cl = layers.get("climate")
    data = (cl.data if cl is not None else None) or {}
    rose = data.get("wind_rose")
    if not rose:
        _empty(ax, "no wind data")
        return
    freqs = np.asarray(rose["frequencies"], dtype=float)  # (n_dir, n_speed)
    n_dir = freqs.shape[0]
    width = 2 * np.pi / n_dir
    theta = np.arange(n_dir) * width
    greys = ["#e0ddd6", "#bdb8ad", "#918a7d", "#635c50", "#332f27"]
    bottom = np.zeros(n_dir)
    labels = (
        rose.get("speed_bin_labels")
        or rose.get("speed_labels")
        or [f"band {i}" for i in range(freqs.shape[1])]
    )
    for j in range(freqs.shape[1]):
        ax.bar(
            theta,
            freqs[:, j],
            width=width * 0.92,
            bottom=bottom,
            color=greys[j % len(greys)],
            edgecolor="none",
            align="edge",
            label=labels[j],
        )
        bottom += freqs[:, j]
    _polar_furniture(ax)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.34),
        ncols=3,
        fontsize=S.FS["micro"],
        handlelength=0.9,
        columnspacing=0.9,
    )


def _polar_furniture(ax: Axes) -> None:
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_yticklabels([])
    ax.set_xticks(np.radians([0, 90, 180, 270]))
    ax.set_xticklabels(["N", "E", "S", "W"], fontsize=S.FS["micro"], color=S.MUTED)
    ax.grid(color=S.FAINT, lw=S.LW["hair"])
    ax.spines["polar"].set_visible(False)
    ax.set_facecolor(S.PAPER)


def sun_path(ax: Axes, aoi: AOI) -> None:
    """Stereographic sun path with the three canonical arcs.

    Stereographic rather than equidistant because it keeps the shape of the arcs
    near the horizon, which is where overshadowing questions actually live.
    """
    lon, lat = aoi.centroid_lonlat
    S.strip(ax)
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)

    # The horizon (altitude 0) and the 45-degree altitude ring, which together
    # give the reader a scale without a numeric axis.
    for radius in (1.0, float(np.tan(np.pi / 8))):
        ax.add_patch(mpatches.Circle((0, 0), radius, fill=False, color=S.RULE, lw=S.LW["hair"]))
    for az in range(0, 360, 30):
        a = math.radians(az)
        ax.plot([0, math.sin(a)], [0, math.cos(a)], color=S.FAINT, lw=S.LW["hair"], zorder=0)
    for az, lbl in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        a = math.radians(az)
        ax.text(
            1.09 * math.sin(a),
            1.09 * math.cos(a),
            lbl,
            ha="center",
            va="center",
            fontsize=S.FS["micro"],
            color=S.MUTED,
        )

    styles = {
        "21 Jun": (S.LW["line"], S.ACCENT),
        "21 Mar / 23 Sep": (S.LW["thin"], S.INK),
        "21 Dec": (S.LW["thin"], S.MUTED),
    }
    for label, pos in key_arcs(lat, lon).items():
        m = pos.above_horizon
        if not m.any():
            continue
        x, y = stereographic(pos.azimuth[m], pos.altitude[m])
        lw, colour = styles.get(label, (S.LW["thin"], S.INK))
        ax.plot(x, y, color=colour, lw=lw, label=label, solid_capstyle="round")
    ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, -0.16), ncols=1, fontsize=S.FS["micro"], handlelength=1.2
    )


def landuse_bars(ax: Axes, metrics: dict[str, Any]) -> None:
    """Two stacked bars: what OSM has mapped, and what the satellite sees.

    The OSM bar carries an explicit unmapped slice. Showing the completeness
    problem is a stronger move than hiding it inside a scalar, and it is exactly
    what a GIS specialist would otherwise ask about.
    """
    lu = metrics.get("landuse") or {}
    osm = _osm_landuse_fractions(lu)
    cover = _landcover_fractions(lu)
    if not osm and not cover:
        _empty(ax, "no land use data")
        return

    rows: list[tuple[str, dict[str, float], dict[str, str]]] = []
    if osm:
        rows.append(("OSM land use", osm, S.LANDUSE_COLOURS))
    if cover:
        rows.append(("ESA WorldCover", cover, _landcover_palette()))

    S.strip(ax)
    ax.set_aspect("auto")
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    for i, (label, fracs, palette) in enumerate(rows):
        left = 0.0
        degraded = label.startswith("OSM") and lu.get("landuse_degraded")
        for key, val in sorted(fracs.items(), key=lambda kv: -kv[1]):
            if val <= 0:
                continue
            colour = palette.get(key, "#dddddd")
            ax.barh(
                i,
                val,
                left=left,
                height=0.5,
                color=colour,
                edgecolor=S.PAPER,
                linewidth=0.6,
                alpha=0.45 if degraded and key != "unmapped" else 1.0,
            )
            if val > 0.09:
                ax.text(
                    left + val / 2,
                    i,
                    f"{key}\n{val:.0%}",
                    ha="center",
                    va="center",
                    fontsize=S.FS["micro"],
                    color=S.PAPER if _dark(colour) else S.INK,
                )
            left += val
        ax.text(0, i + 0.36, label, fontsize=S.FS["micro"], color=S.MUTED, va="bottom")
    ax.invert_yaxis()


def _osm_landuse_fractions(lu: dict[str, Any]) -> dict[str, float]:
    """Unpack the flat `landuse_<class>_fraction` keys the metric emits.

    The unmapped slice is included deliberately, so the bar sums to 1.0 and the
    reader sees how much of the AOI OSM simply has no answer for.
    """
    out: dict[str, float] = {}
    for key, val in lu.items():
        if not key.startswith("landuse_") or not key.endswith("_fraction"):
            continue
        if not isinstance(val, (int, float)):
            continue
        out[key[len("landuse_") : -len("_fraction")]] = float(val)
    return out


def _landcover_palette() -> dict[str, str]:
    """Class name to colour, derived from the provider so the raster panel and
    the bar can never disagree about what green means."""
    try:
        from ..providers.landcover_worldcover import CLASS_COLOURS, CLASSES
    except ImportError:
        return {}
    return {name: CLASS_COLOURS.get(code, "#dddddd") for code, name in CLASSES.items()}


def _landcover_fractions(lu: dict[str, Any]) -> dict[str, float]:
    """Unpack `landcover_class_<code>_fraction` into readable class names."""
    try:
        from ..providers.landcover_worldcover import CLASSES
    except ImportError:
        return {}
    out: dict[str, float] = {}
    for key, val in lu.items():
        if not key.startswith("landcover_class_") or not key.endswith("_fraction"):
            continue
        if not isinstance(val, (int, float)):
            continue
        try:
            code = int(key[len("landcover_class_") : -len("_fraction")])
        except ValueError:
            continue
        out[CLASSES.get(code, f"class {code}")] = float(val)
    return out


def _dark(hex_colour: str) -> bool:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) < 140


def locator(ax: Axes, aoi: AOI) -> None:
    """A minimal world locator. No basemap tile: a slippy map would make this a
    screenshot rather than a drawing."""
    S.strip(ax, keep_frame=True)
    lon, lat = aoi.centroid_lonlat
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_aspect("equal")
    for y in range(-60, 90, 30):
        ax.axhline(y, color=S.FAINT, lw=S.LW["hair"])
    for x in range(-150, 180, 30):
        ax.axvline(x, color=S.FAINT, lw=S.LW["hair"])
    ax.axhline(0, color=S.RULE, lw=S.LW["thin"])
    ax.plot([lon], [lat], marker="+", color=S.ACCENT, ms=9, mew=1.1)
    ax.text(
        lon,
        lat - 12,
        f"{abs(lat):.2f}{'N' if lat >= 0 else 'S'}  {abs(lon):.2f}{'E' if lon >= 0 else 'W'}",
        ha="center",
        va="top",
        fontsize=S.FS["micro"],
        color=S.MUTED,
    )


def _empty(ax: Axes, msg: str) -> None:
    S.strip(ax)
    ax.text(
        0.5,
        0.5,
        msg,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=S.FS["small"],
        color=S.MUTED,
        style="italic",
    )
