"""Shared square-metre-grid reprojection helpers for terrain providers.

Both the Copernicus GLO-30 DSM provider and the FABDEM DTM provider read one
or more geographic tiles, merge them, and must reproject that merged array
onto a square metre grid in the AOI's own CRS *before* any slope computation
happens downstream (CONTRIBUTING.md trap #3: "reproject the DEM window to a
square metre grid before computing slope"). Extracted here once so a second
raster terrain provider does not copy-paste the first one's windowing and
reprojection code.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from affine import Affine
from rasterio.warp import Resampling, reproject

from ..raster import inside_mask


def reproject_merged_to_square_grid(
    merged_arr: np.ndarray,
    merged_transform: Affine,
    src_crs: Any,
    aoi: Any,
    resolution_m: float,
) -> tuple[np.ndarray, Affine]:
    """Reproject a merged geographic-tile array onto a square AOI-CRS grid.

    Returns `(array, transform)` in `aoi.crs`, at `resolution_m` spacing, with
    `nan` outside the source coverage. Callers must do this before touching
    slope or aspect.
    """
    minx, miny, maxx, maxy = aoi.bounds_metric
    width = max(1, math.ceil((maxx - minx) / resolution_m))
    height = max(1, math.ceil((maxy - miny) / resolution_m))
    dst_transform = Affine(resolution_m, 0.0, minx, 0.0, -resolution_m, maxy)
    dst_arr = np.full((height, width), np.nan, dtype=np.float32)

    reproject(
        source=merged_arr,
        destination=dst_arr,
        src_transform=merged_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=aoi.crs,
        resampling=Resampling.bilinear,
        src_nodata=None,
        dst_nodata=np.nan,
    )
    dst_arr[~inside_mask(dst_arr.shape, dst_transform, aoi)] = np.nan
    return dst_arr, dst_transform


def elevation_summary(values: np.ndarray) -> dict[str, float | None]:
    """min/max/mean of the valid elevations (1D, e.g. `SiteRaster.values_inside()`)."""
    return {
        "min_elevation_m": float(values.min()) if values.size else None,
        "max_elevation_m": float(values.max()) if values.size else None,
        "mean_elevation_m": float(values.mean()) if values.size else None,
    }
