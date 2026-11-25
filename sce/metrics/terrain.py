"""Terrain metrics from a projected elevation raster.

`terrain_model` is read from the provider's own declaration
(`layers["terrain"].data["terrain_model"]`), defaulting to "DSM" only when a
provider does not state one. Copernicus GLO-30, the global default elevation
source behind `layers["terrain"]`, is a digital SURFACE model — it includes
rooftops and tree canopy, not bare ground — which is why "DSM" is the safe
default rather than "DTM". FABDEM (`sce/providers/terrain_fabdem.py`, opt-in
via `--dtm fabdem`) declares "DTM" instead, because it is bare earth. Slope
and aspect computed from a DSM will read steeper and noisier over built-up or
wooded ground than a true DTM would. That caveat belongs on the sheet next to
every number this module produces, not just in a footnote.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..aoi import AOI, assert_metric_crs
from ..types import LayerResult

BUILDABLE_SLOPE_DEG = np.degrees(np.arctan(1.0 / 20.0))  # 1:20 practical buildable threshold
_SLOPE_TOLERANCE_DEG = 1e-9  # absorbs float rounding from np.gradient, not real slope

_ASPECT_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _dominant_aspect(aspect_deg: np.ndarray, flat_mask: np.ndarray) -> str | None:
    valid = aspect_deg[~flat_mask]
    if valid.size == 0:
        return None
    bin_width = 360.0 / len(_ASPECT_DIRECTIONS)
    shifted = (valid + bin_width / 2.0) % 360.0
    bins = (shifted // bin_width).astype(int) % len(_ASPECT_DIRECTIONS)
    counts = np.bincount(bins, minlength=len(_ASPECT_DIRECTIONS))
    return _ASPECT_DIRECTIONS[int(np.argmax(counts))]


def terrain_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    terrain = layers["terrain"]
    raster = terrain.raster
    if raster is None:
        raise ValueError("terrain_metrics requires layers['terrain'].raster")
    assert_metric_crs(raster.crs, where="terrain_metrics")

    array = raster.float_array()
    dx, dy = raster.res

    dzdy, dzdx = np.gradient(array, dy, dx)
    slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
    slope_deg = np.degrees(slope_rad)

    aspect_rad = np.arctan2(-dzdx, dzdy)
    aspect_deg = (np.degrees(aspect_rad) + 360.0) % 360.0

    valid = ~np.isnan(slope_deg)
    n_valid = int(valid.sum())
    if n_valid == 0:
        raise ValueError("terrain_metrics: raster contains no valid elevation pixels")

    flat_mask = valid & (slope_deg < 1e-6)

    terrain_model = (terrain.data or {}).get("terrain_model") or "DSM"
    terrain_model_note = (
        "Bare-earth DTM (FABDEM v1.2): canopy and building height are removed."
        if terrain_model == "DTM"
        else "Copernicus GLO-30 is a digital surface model: elevations include "
        "rooftops and tree canopy, not bare ground. Slope and aspect here "
        "inherit that bias."
    )

    result: dict[str, Any] = {
        "slope_mean_deg": float(np.nanmean(slope_deg)),
        "slope_mean_pct": float(np.nanmean(np.tan(slope_rad)) * 100.0),
        "buildable_fraction_under_1_20": float(
            np.sum(valid & (slope_deg <= BUILDABLE_SLOPE_DEG + _SLOPE_TOLERANCE_DEG)) / n_valid
        ),
        "elevation_min_m": float(np.nanmin(array)),
        "elevation_max_m": float(np.nanmax(array)),
        "elevation_mean_m": float(np.nanmean(array)),
        "elevation_range_m": float(np.nanmax(array) - np.nanmin(array)),
        "dominant_aspect": _dominant_aspect(aspect_deg[valid], flat_mask[valid]),
        "terrain_model": terrain_model,
        "terrain_model_note": terrain_model_note,
    }
    return result


terrain_metrics.REQUIRES = ("terrain",)
