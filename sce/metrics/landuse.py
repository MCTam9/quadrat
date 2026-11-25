"""Land-use (OSM) and land-cover (ESA WorldCover) metrics.

Deliberately NOT computed here: a land-use mix entropy scalar. OSM `landuse`
tagging is wildly incomplete outside a handful of well-mapped cities — the
"unmapped" fraction below is routinely 40-70% of an AOI. An entropy computed
over the mapped remainder would report a single confident-looking number that
is precisely wrong: it describes the tagging effort, not the site. Showing the
unmapped slice honestly, and leaving the reader to weigh the mapped fractions
themselves, is the more truthful choice than manufacturing a summary statistic
a subset of the ground cannot support.

ESA WorldCover fills that hole with satellite-derived ground truth: it has no
"unmapped" fraction because it classifies every pixel, so its class fractions
are reported separately rather than merged with OSM's.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely import make_valid

from ..aoi import AOI, assert_metric_crs
from ..types import LayerResult
from ..vocab import LANDUSE_IDS, normalise_landuse

LANDUSE_DEGRADED_THRESHOLD = 0.5


def _normalise_class(raw: str | None) -> str:
    return normalise_landuse(raw)


def _class_area(geoms) -> float:
    valid = [make_valid(g) for g in geoms if g is not None and not g.is_empty]
    if not valid:
        return 0.0
    import shapely

    return float(shapely.union_all(valid).area)


# Land-use polygons overlap freely in OSM: a park is tagged inside a residential
# zone, a school sits inside an institutional block. Summing per-class union
# areas therefore exceeds the mapped area and the bar runs past 100%. Classes are
# instead allocated disjointly in this order, most specific first, each class
# taking only the ground no earlier class has already claimed.
ALLOCATION_ORDER = LANDUSE_IDS


def _osm_landuse_fractions(gdf, aoi: AOI) -> dict[str, Any]:
    """Disjoint area share per class, plus the explicit unmapped remainder.

    The fractions and the unmapped slice sum to exactly 1.0, so the stacked bar
    on the sheet is a true partition of the site rather than a set of overlapping
    claims that happen to add up to more than the ground available.
    """
    import shapely

    result: dict[str, Any] = {}
    column = "class" if (gdf is not None and "class" in gdf.columns) else "landuse"
    if gdf is None or len(gdf) == 0 or column not in gdf.columns:
        result["landuse_unmapped_fraction"] = 1.0
        result["landuse_degraded"] = True
        return result

    classes = gdf[column].map(_normalise_class)
    present = list(classes.unique())
    ordered = [c for c in ALLOCATION_ORDER if c in present]
    ordered += [c for c in sorted(present) if c not in ordered]

    claimed = None
    mapped_area = 0.0
    for cls in ordered:
        geoms = [
            make_valid(g)
            for g in gdf.loc[classes == cls, gdf.geometry.name].values
            if g is not None and not g.is_empty
        ]
        if not geoms:
            result[f"landuse_{cls}_fraction"] = 0.0
            continue
        merged = shapely.union_all(geoms)
        exclusive = merged if claimed is None else merged.difference(claimed)
        area = float(exclusive.area) if not exclusive.is_empty else 0.0
        result[f"landuse_{cls}_fraction"] = area / aoi.area_m2 if aoi.area_m2 else 0.0
        mapped_area += area
        claimed = merged if claimed is None else shapely.union_all([claimed, merged])

    mapped_area = min(mapped_area, aoi.area_m2)
    unmapped_fraction = max(0.0, 1.0 - (mapped_area / aoi.area_m2 if aoi.area_m2 else 0.0))
    result["landuse_unmapped_fraction"] = unmapped_fraction
    result["landuse_degraded"] = (1.0 - unmapped_fraction) < LANDUSE_DEGRADED_THRESHOLD
    return result


def _landcover_fractions(raster: dict[str, Any] | None) -> dict[str, Any]:
    if raster is None:
        return {"landcover_source": "no ESA WorldCover raster available"}
    array = raster["array"]
    nodata = raster.get("nodata")
    valid_mask = np.ones_like(array, dtype=bool) if nodata is None else array != nodata
    valid = array[valid_mask]
    total = valid.size
    result: dict[str, Any] = {}
    if total == 0:
        result["landcover_source"] = "raster contained no valid pixels over the AOI"
        return result
    codes, counts = np.unique(valid, return_counts=True)
    for code, count in zip(codes, counts, strict=False):
        result[f"landcover_class_{int(code)}_fraction"] = float(count) / float(total)
    return result


def landuse_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    landuse = layers.get("landuse")
    landcover = layers.get("landcover")

    if landuse is not None and landuse.gdf is not None:
        assert_metric_crs(landuse.gdf.crs, where="landuse_metrics")
    elif landcover is not None and landcover.raster is not None:
        assert_metric_crs(landcover.raster.get("crs"), where="landuse_metrics")
    else:
        assert_metric_crs(aoi.crs, where="landuse_metrics")

    result: dict[str, Any] = {}
    result.update(_osm_landuse_fractions(landuse.gdf if landuse is not None else None, aoi))
    result.update(_landcover_fractions(landcover.raster if landcover is not None else None))
    return result


landuse_metrics.REQUIRES = ()
