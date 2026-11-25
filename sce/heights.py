"""Per-building heights sampled from a measured nDSM (LiDAR).

OSM leaves most footprints without a height tag, which is why FSI normally
falls back to a 100 m regional mean. When a `building_height` raster of kind
"ndsm" exists (see sce/providers/height_ea_lidar.py) the footprints can be
measured directly instead. A footprint that cannot be measured stays unknown:
a missing height is never filled with a guess.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from rasterio.features import geometry_mask
from rasterio.transform import Affine

from .providers._buildings import summarise_building_heights
from .registry import REGISTRY
from .types import LayerResult

MIN_CELL_HEIGHT_M = 2.0
MIN_CELLS = 5
PERCENTILE = 90.0


def _has_height(value: object) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _sample(geom, array: np.ndarray, transform: Affine) -> float | None:
    """90th percentile of cells above MIN_CELL_HEIGHT_M inside `geom`, else None."""
    if geom is None or geom.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    inv = ~transform
    cols = [inv * (x, y) for x, y in ((minx, miny), (maxx, maxy))]
    c0 = max(0, math.floor(min(c[0] for c in cols)))
    c1 = min(array.shape[1], math.ceil(max(c[0] for c in cols)))
    r0 = max(0, math.floor(min(c[1] for c in cols)))
    r1 = min(array.shape[0], math.ceil(max(c[1] for c in cols)))
    if c1 <= c0 or r1 <= r0:
        return None
    win_transform = transform @ Affine.translation(c0, r0)
    inside = geometry_mask([geom], out_shape=(r1 - r0, c1 - c0), transform=win_transform, invert=True)
    cells = array[r0:r1, c0:c1][inside]
    cells = cells[np.isfinite(cells) & (cells > MIN_CELL_HEIGHT_M)]
    if cells.size < MIN_CELLS:
        return None
    return float(np.percentile(cells, PERCENTILE))


def enrich_building_heights(
    layers: dict[str, LayerResult], *, prefer_lidar: bool = False
) -> dict[str, LayerResult]:
    """Return a copy of `layers` whose buildings carry LiDAR heights where measurable.

    Buildings without a finite `height_m` get `height_source = "lidar"` when at
    least MIN_CELLS nDSM cells above MIN_CELL_HEIGHT_M fall inside the
    footprint. With `prefer_lidar`, tagged heights are replaced by a LiDAR
    measurement whenever one is available. Inputs are never mutated.
    """
    height = layers.get("building_height")
    buildings = layers.get("buildings")
    raster = None if height is None else height.raster
    if (
        raster is None
        or raster.get("kind") != "ndsm"
        or buildings is None
        or buildings.gdf is None
        or len(buildings.gdf) == 0
    ):
        return dict(layers)

    gdf = buildings.gdf.copy()
    if "height_m" not in gdf.columns:
        gdf["height_m"] = np.nan
    if "height_source" not in gdf.columns:
        gdf["height_source"] = None
    gdf["height_m"] = gdf["height_m"].astype(float)
    gdf["height_source"] = gdf["height_source"].astype(object)

    array, transform = raster["array"], raster["transform"]
    heights = gdf["height_m"].to_numpy(copy=True)
    sources = gdf["height_source"].to_numpy(copy=True)
    for i, geom in enumerate(gdf.geometry):
        if _has_height(heights[i]) and not prefer_lidar:
            continue
        measured = _sample(geom, array, transform)
        if measured is not None:
            heights[i] = measured
            sources[i] = "lidar"
    gdf["height_m"] = heights
    gdf["height_source"] = sources

    notes = list(buildings.notes)
    n_lidar = int((sources == "lidar").sum())
    if n_lidar:
        notes.append(f"{n_lidar} building heights measured from LiDAR nDSM ({height.provider})")
    new_buildings = replace(
        buildings,
        gdf=gdf,
        notes=notes,
        sources=list(buildings.sources) + [s for s in height.sources if s not in buildings.sources],
    )
    # Coverage, degraded and findings are the buildings provider's own rule,
    # re-run now that LiDAR heights are filled in.
    provider = REGISTRY.provider(buildings.provider)
    new_buildings = (
        provider.summarise(new_buildings, None)
        if provider is not None
        else summarise_building_heights(new_buildings)
    )
    out = dict(layers)
    out["buildings"] = new_buildings
    return out
