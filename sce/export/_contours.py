"""Contour tracing shared by every vector exporter (DXF, Rhino, SVG).

One implementation, so the contours in a DXF, a 3DM and an SVG of the same
site are the same lines at the same levels.
"""

from __future__ import annotations

from typing import Any

import numpy as np

CONTOUR_INTERVALS = (1.0, 2.0, 5.0, 10.0, 25.0)


def choose_contour_interval(zmin: float, zmax: float) -> float:
    """Pick the smallest standard interval giving at most ~8 contour levels.

    More than that and a flat-ish site turns into a solid smear of lines.
    """
    span = max(zmax - zmin, 1e-6)
    target = span / 8.0
    for interval in CONTOUR_INTERVALS:
        if interval >= target:
            return interval
    return CONTOUR_INTERVALS[-1]


def contour_segments(
    array: np.ndarray, transform: Any, interval: float
) -> list[tuple[float, list[tuple[float, float]]]]:
    """(elevation, [(x, y), ...]) pairs in metric coordinates.

    X/Y are built from the affine transform up front, so contour vertices come out
    already in metric CRS coordinates with no separate reprojection step. Traced
    with contourpy using the "mpl2014" algorithm, which is what matplotlib's
    `ax.contour` runs, so the lines match what matplotlib drew before; using it
    directly keeps matplotlib (PDF sheet only) out of the site API's bundle.
    """
    import contourpy

    rows, cols = array.shape
    row_idx, col_idx = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    xs, ys = transform @ (col_idx + 0.5, row_idx + 0.5)

    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return []
    zmin, zmax = float(finite.min()), float(finite.max())
    if zmax - zmin < 1e-9:
        return []
    levels = list(np.arange(np.floor(zmin / interval) * interval, zmax + interval, interval))
    levels = [lv for lv in levels if zmin < lv < zmax]
    if not levels:
        return []

    gen = contourpy.contour_generator(
        np.asarray(xs, dtype=float),
        np.asarray(ys, dtype=float),
        np.ma.masked_invalid(np.asarray(array, dtype=float)),
        name="mpl2014",
        line_type=contourpy.LineType.SeparateCode,
    )
    out: list[tuple[float, list[tuple[float, float]]]] = []
    for level in levels:
        segs, _codes = gen.lines(level)  # mpl2014 only offers SeparateCode; codes are not needed
        out.extend((float(level), [(float(x), float(y)) for x, y in seg]) for seg in segs if len(seg) >= 2)
    return out


def terrain_contours(result: Any) -> list[tuple[float, list[tuple[float, float]]]]:
    """Contours for a terrain `LayerResult`, at an automatically chosen interval.

    Returns [] when there is no usable raster, so callers need no guards.
    """
    if result is None or result.raster is None:
        return []
    array = result.raster.float_array()
    transform = result.raster.transform
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return []
    interval = choose_contour_interval(float(finite.min()), float(finite.max()))
    return contour_segments(array, transform, interval)
