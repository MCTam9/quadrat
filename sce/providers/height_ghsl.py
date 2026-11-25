"""GHS-BUILT-H R2023A building-height FALLBACK, for when OSM height tagging
is too sparse for floor space index to be trusted (verified: Tashkent ~10%,
Riyadh ~1% of OSM footprints carry a height or levels tag).

GHS-BUILT-H gives average net building height (ANBH) at 100 m resolution,
globally, free of charge, licensed CC BY 4.0 (European Commission, Joint
Research Centre, reuse decision 2011/833/EU). This is NOT a `buildings`
footprint provider — it feeds a distinct `building_height` layer that
`sce/metrics/fabric.py` consults only when the OSM height coverage on the
`buildings` layer is below threshold.

Distribution reality, confirmed by hand against the live endpoint before
writing this module: GHS-BUILT-H is published as 1000 km x 1000 km tiles in
World Mollweide (ESRI:54009), and each tile is a ZIPPED single-band GeoTIFF —
there is no COG endpoint that supports HTTP range reads of a sub-window the
way `terrain_copernicus.py` does against the Copernicus DEM bucket. A zip's
central directory and DEFLATE stream are not addressable by byte-range in a
way GDAL's /vsizip//vsicurl/ can exploit for a single-window read without
pulling the whole archive, so this provider downloads and caches the whole
tile (~8-10 MB per 1000 km tile at this resolution, confirmed by HEAD
request) rather than windowing it. An AOI a few km wide costs one such
download, cached forever after by `sce.cache.Cache`.

URL pattern, confirmed with a live GET against the JRC data endpoint on
2026-09-06:

    https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_H_GLOBE_R2023A/
    GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100/V1-0/tiles/
    GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}.zip

Tile grid: interior tiles are exactly 1,000,000 x 1,000,000 m in Mollweide,
with column 1's west edge at x=-18,041,000 m and row 1's north edge at
y=9,000,000 m (edge tiles nearer the poles or the antimeridian are cropped to
the data extent, but no AOI this tool targets sits there). This was derived
empirically from three downloaded tiles' bounds and confirmed by fetching the
tile computed for Tashkent (69.2401, 41.2995) and reading back a real ANBH
value (2.5 m) at that exact point.
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import replace

import numpy as np
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.io import MemoryFile
from rasterio.merge import merge as rio_merge
from rasterio.warp import Resampling, reproject

from ..raster import SiteRaster
from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source

MOLLWEIDE = CRS.from_user_input("ESRI:54009")
BASE_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_H_GLOBE_R2023A/"
    "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100/V1-0/tiles"
)
TILE_TEMPLATE = "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}"
TILE_SIZE_M = 1_000_000.0
GRID_ORIGIN_X = -18_041_000.0  # west edge of column 1, Mollweide metres
GRID_ORIGIN_Y_TOP = 9_000_000.0  # north edge of row 1, Mollweide metres
RESOLUTION_M = 100.0
NODATA_SENTINEL = 255.0  # ANBH tiles use this as the nodata flag, not a real height


def _tile_rc(x: float, y: float) -> tuple[int, int]:
    col = math.floor((x - GRID_ORIGIN_X) / TILE_SIZE_M) + 1
    row = math.floor((GRID_ORIGIN_Y_TOP - y) / TILE_SIZE_M) + 1
    return row, col


def _tile_url(row: int, col: int) -> str:
    name = TILE_TEMPLATE.format(row=row, col=col)
    return f"{BASE_URL}/{name}.zip"


class GhslBuildingHeightProvider(Provider):
    """GHS-BUILT-H ANBH 100 m raster, whole-tile cached, reprojected to the AOI."""

    name = "ghsl_building_height"
    layer = "building_height"
    licence = "CC BY 4.0 (EC reuse decision 2011/833/EU)"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        to_mollweide = Transformer.from_crs(aoi.crs, MOLLWEIDE, always_xy=True)
        corners_x, corners_y = zip(
            *(to_mollweide.transform(x, y) for x, y in aoi.geometry.exterior.coords), strict=False
        )
        minx, maxx = min(corners_x), max(corners_x)
        miny, maxy = min(corners_y), max(corners_y)
        row0, col0 = _tile_rc(minx, maxy)
        row1, col1 = _tile_rc(maxx, miny)
        row_lo, row_hi = min(row0, row1), max(row0, row1)
        col_lo, col_hi = min(col0, col1), max(col0, col1)

        memfiles = []
        datasets = []
        try:
            for row in range(row_lo, row_hi + 1):
                for col in range(col_lo, col_hi + 1):
                    url = _tile_url(row, col)
                    key = cache.key("ghsl-building-height", url)
                    blob, _meta = cache.get_bytes(key, ".zip", self._make_producer(url))
                    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                        tif_name = next(n for n in zf.namelist() if n.lower().endswith(".tif"))
                        tif_bytes = zf.read(tif_name)
                    memfile = MemoryFile(tif_bytes)
                    memfiles.append(memfile)
                    datasets.append(memfile.open())

            if not datasets:
                raise RuntimeError("ghsl_building_height: no tiles intersect AOI")

            merged_arr, merged_transform = rio_merge(datasets, nodata=NODATA_SENTINEL)
            merged_arr = merged_arr[0].astype(np.float32)
            merged_arr[merged_arr == NODATA_SENTINEL] = np.nan
        finally:
            for ds in datasets:
                ds.close()
            for mf in memfiles:
                mf.close()

        minx_m, miny_m, maxx_m, maxy_m = aoi.bounds_metric
        width = max(1, math.ceil((maxx_m - minx_m) / RESOLUTION_M))
        height = max(1, math.ceil((maxy_m - miny_m) / RESOLUTION_M))
        dst_transform = Affine(RESOLUTION_M, 0.0, minx_m, 0.0, -RESOLUTION_M, maxy_m)
        dst_arr = np.full((height, width), np.nan, dtype=np.float32)

        reproject(
            source=merged_arr,
            destination=dst_arr,
            src_transform=merged_transform,
            src_crs=MOLLWEIDE,
            dst_transform=dst_transform,
            dst_crs=aoi.crs,
            resampling=Resampling.bilinear,
            src_nodata=np.nan,
            dst_nodata=np.nan,
        )

        source = Source(
            name="GHS-BUILT-H R2023A (ANBH), European Commission JRC",
            url=BASE_URL,
            licence=self.licence,
            licence_url="https://data.jrc.ec.europa.eu/licence/com_reuse",
            note=(
                "Average net building height (ANBH) at 100 m in World Mollweide, downloaded as "
                "whole zipped tiles (no COG range-read endpoint exists for this dataset) and "
                "reprojected to a square metre grid in the AOI CRS."
            ),
            commercial_ok=True,
        )

        return self.summarise(
            LayerResult(
                layer=self.layer,
                provider=self.name,
                raster=SiteRaster.from_array(
                    dst_arr,
                    dst_transform,
                    aoi.crs,
                    square=aoi,
                    nodata=float("nan"),
                    blank_outside=True,
                ),
                sources=[source],
                notes=[
                    "GHS-BUILT-H ANBH is a 2018-epoch 100 m average net building height raster, a "
                    "fallback for FSI where OSM height tagging is too sparse to trust, not a "
                    "footprint source: it carries no per-building geometry.",
                    f"Reprojected to {aoi.epsg} on a square {RESOLUTION_M:.0f} m grid "
                    "(rasterio.warp.reproject, Resampling.bilinear).",
                ],
            ),
            aoi,
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        """Coverage and mean (cells > 0) over the cells inside the square."""
        raster = result.raster
        coverage = raster.share_known()
        valid = raster.values_inside(lambda v: v > 0.0)
        data = {**(result.data or {}), "mean_height_m": float(valid.mean()) if valid.size else None}
        return replace(result, data=data, coverage=coverage, degraded=coverage < 0.5, findings=[])

    @staticmethod
    def _make_producer(url: str):
        def _producer() -> tuple[bytes, dict]:
            import requests

            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            return resp.content, {"url": url, "licence": "CC BY 4.0 (EC reuse decision 2011/833/EU)"}

        return _producer


REGISTRY.register(GhslBuildingHeightProvider())
