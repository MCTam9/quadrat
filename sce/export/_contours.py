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

    `matplotlib.contour.ContourSet.allsegs` returns, per requested level, a
    list of (N, 2) arrays already in whatever coordinate system X/Y were
    given in, so building X/Y from the affine transform up front means the
    contour vertices come out already in metric CRS coordinates, no separate
    reprojection step needed. `allsegs` is deprecated in newer matplotlib but
    still present in 3.11.x; if a future upgrade removes it, `get_paths()` is
    the fallback.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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

    fig, ax = plt.subplots()
    try:
        cs = ax.contour(xs, ys, array, levels=levels)
        out: list[tuple[float, list[tuple[float, float]]]] = []
        if hasattr(cs, "allsegs"):
            for level, segs in zip(cs.levels, cs.allsegs, strict=False):
                out.extend(
                    (float(level), [(float(x), float(y)) for x, y in seg]) for seg in segs if len(seg) >= 2
                )
        else:  # pragma: no cover - fallback for matplotlib >= 3.10 collections removal
            for level, path in zip(cs.levels, cs.get_paths(), strict=False):
                out.extend(
                    (float(level), [(float(x), float(y)) for x, y in polygon])
                    for polygon in path.to_polygons()
                    if len(polygon) >= 2
                )
        return out
    finally:
        plt.close(fig)


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
