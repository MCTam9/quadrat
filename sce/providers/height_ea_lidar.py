"""Measured building heights for England from Environment Agency LiDAR.

nDSM = DSM - DTM from the Environment Agency National LiDAR Programme
composites, served key-free by the Defra Data Services Platform as OGC WCS 2.0.1
in EPSG:27700 (British National Grid), Open Government Licence v3.0:

    https://environment.data.gov.uk/spatialdata/
      lidar-composite-digital-surface-model-last-return-dsm-1m/wcs   (DSM, last return)
      lidar-composite-digital-terrain-model-dtm-1m/wcs               (DTM)

Verified live on 2026-11-25 (London, 530016 E 180335 N): GetCoverage with
`format=image/tiff&subset=E(a,b)&subset=N(c,d)` returns an uncompressed
float32 GeoTIFF at 1 m with nodata -3.4e38. There is no documented request size
cap, but responses are uncompressed (4 MB per km^2, roughly 5 s per km^2 and
super-linear beyond ~2 km), so requests are tiled into 1 km BNG-aligned squares,
which also makes each cache entry reusable by neighbouring sites.

The DSM is last-return: it keeps roofs but drops part of the tree canopy, and
survey epochs differ between tiles (2000s to 2022). Coverage is England only and
patchy; where the service returns nothing the provider raises so the registry
falls through to GHS-BUILT-H.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._terrain_grid import inside_aoi, reproject_merged_to_square_grid

BASE = "https://environment.data.gov.uk/spatialdata"
DSM_URL = f"{BASE}/lidar-composite-digital-surface-model-last-return-dsm-1m/wcs"
DSM_COVERAGE = "9ba4d5ac-d596-445a-9056-dae3ddec0178__Lidar_Composite_Elevation_LZ_DSM_1m"
DTM_URL = f"{BASE}/lidar-composite-digital-terrain-model-dtm-1m/wcs"
DTM_COVERAGE = "13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m"
LICENCE = "Open Government Licence v3.0"
LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"

TILE_M = 1000
MAX_TILES = 36
RETRIES = 2
REQUEST_TIMEOUT_S = 30  # a healthy 1 km tile takes ~3-5 s; the service sometimes stalls
# Whole-layer budget. Tiles download concurrently; if the service stalls past
# this, give up so the registry falls through to GHSL instead of eating the
# web request's time limit. Override with SCE_LIDAR_BUDGET_S.
BUDGET_S = 75.0
MAX_WORKERS = 8
BUILDING_LIKE_MIN_M = 2.5
_BNG = "EPSG:27700"
_NODATA_FLOOR = -1e30


def in_england(lon: float, lat: float) -> bool:
    """Coarse England test: bbox minus the Welsh/Scottish corners it would include."""
    if not (-5.8 <= lon <= 1.8 and 49.85 <= lat <= 55.82):
        return False
    if lat > 55.0 and lon < -2.2:
        return False
    return not (lon < -2.95 and 51.3 < lat < 53.4)


def _fetch_tile(url: str, coverage: str, x0: int, y0: int, x1: int, y1: int, cache):
    import requests

    params = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "coverageId": coverage,
        "format": "image/tiff",
        "subset": [f"E({x0},{x1})", f"N({y0},{y1})"],
    }
    key = cache.key("ea-lidar", url, coverage, x0, y0, x1, y1)

    def producer() -> tuple[bytes, dict[str, Any]]:
        last: Exception | None = None
        for _attempt in range(RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
                resp.raise_for_status()
            except requests.RequestException as exc:
                last = exc
                continue
            if resp.content[:4] not in (b"II*\x00", b"MM\x00*"):
                raise RuntimeError(f"EA WCS returned a non-GeoTIFF body: {resp.content[:200]!r}")
            return resp.content, {"url": resp.url, "licence": LICENCE}
        raise RuntimeError(f"EA WCS request failed after {RETRIES} attempts: {last}")

    blob, _meta = cache.get_bytes(key, ".tif", producer)
    return blob


def _fetch_all(specs: list[tuple[str, str, int, int, int, int]], cache) -> dict[tuple, bytes]:
    """Download every tile concurrently, within the layer budget."""
    import os
    from concurrent.futures import ThreadPoolExecutor, wait

    budget = float(os.environ.get("SCE_LIDAR_BUDGET_S", BUDGET_S))
    pool = ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(specs)))
    try:
        futures = {spec: pool.submit(_fetch_tile, *spec, cache) for spec in specs}
        _done, pending = wait(futures.values(), timeout=budget)
        if pending:
            raise RuntimeError(f"ea_lidar_ndsm: {len(pending)} tiles still pending after {budget:.0f} s")
        return {spec: f.result() for spec, f in futures.items()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _read(blob: bytes) -> tuple[np.ndarray, Any]:
    with MemoryFile(blob) as mf, mf.open() as ds:
        arr = ds.read(1).astype(np.float32)
        nodata = ds.nodata
        transform = ds.transform
    arr[arr < _NODATA_FLOOR] = np.nan
    if nodata is not None and np.isfinite(nodata):
        arr[arr == nodata] = np.nan
    return arr, transform


class EaLidarBuildingHeightProvider(Provider):
    """1 m nDSM (DSM - DTM) from EA LiDAR, England only, resampled to the AOI grid."""

    name = "ea_lidar_ndsm"
    layer = "building_height"
    licence = LICENCE
    rank = 5
    commercial_ok = True

    def available(self, aoi) -> bool:
        lon, lat = aoi.centroid_lonlat
        return in_england(lon, lat)

    def fetch(self, aoi, cache) -> LayerResult:
        to_bng = Transformer.from_crs("EPSG:4326", _BNG, always_xy=True)
        pts = [to_bng.transform(x, y) for x, y in aoi.geometry_wgs84.exterior.coords]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        gx0 = math.floor(min(xs) / TILE_M) * TILE_M
        gy0 = math.floor(min(ys) / TILE_M) * TILE_M
        gx1 = math.ceil(max(xs) / TILE_M) * TILE_M
        gy1 = math.ceil(max(ys) / TILE_M) * TILE_M
        nx, ny = (gx1 - gx0) // TILE_M, (gy1 - gy0) // TILE_M
        if nx * ny > MAX_TILES:
            raise RuntimeError(f"ea_lidar_ndsm: AOI needs {nx * ny} 1 km tiles (max {MAX_TILES}); too large")

        width, height = nx * TILE_M, ny * TILE_M
        ndsm = np.full((height, width), np.nan, dtype=np.float32)
        blobs = _fetch_all(
            [
                (url, cov, gx0 + i * TILE_M, gy0 + j * TILE_M, gx0 + (i + 1) * TILE_M, gy0 + (j + 1) * TILE_M)
                for i in range(nx)
                for j in range(ny)
                for url, cov in ((DSM_URL, DSM_COVERAGE), (DTM_URL, DTM_COVERAGE))
            ],
            cache,
        )
        for i in range(nx):
            for j in range(ny):
                x0, y0 = gx0 + i * TILE_M, gy0 + j * TILE_M
                x1, y1 = x0 + TILE_M, y0 + TILE_M
                dsm, t_dsm = _read(blobs[(DSM_URL, DSM_COVERAGE, x0, y0, x1, y1)])
                dtm, t_dtm = _read(blobs[(DTM_URL, DTM_COVERAGE, x0, y0, x1, y1)])
                if dsm.shape != dtm.shape or t_dsm != t_dtm:
                    raise RuntimeError("ea_lidar_ndsm: DSM and DTM tiles are not co-registered")
                row = round(gy1 - t_dsm.f)
                col = round(t_dsm.c - gx0)
                h, w = dsm.shape
                ndsm[row : row + h, col : col + w] = dsm - dtm

        if not np.isfinite(ndsm).any():
            raise RuntimeError("ea_lidar_ndsm: no LiDAR coverage returned for this AOI")

        mosaic_transform = Affine(1.0, 0.0, gx0, 0.0, -1.0, gy1)
        span = max(aoi.bounds_metric[2] - aoi.bounds_metric[0], 1.0)
        res = 1.0 if span <= 3000 else 2.0
        arr, transform = reproject_merged_to_square_grid(ndsm, mosaic_transform, _BNG, aoi, res)
        arr = np.where(np.isfinite(arr), np.maximum(arr, 0.0), np.nan).astype(np.float32)

        source = Source(
            name="Environment Agency National LiDAR Programme composite DSM (last return) and DTM, 1 m",
            url=f"{BASE}/ (WCS, EPSG:27700)",
            licence=LICENCE,
            licence_url=LICENCE_URL,
            note="Contains Environment Agency information (c) Environment Agency and/or database right.",
            commercial_ok=True,
        )
        return self.summarise(
            LayerResult(
                layer=self.layer,
                provider=self.name,
                raster={
                    "array": arr,
                    "transform": transform,
                    "crs": aoi.crs,
                    "nodata": float("nan"),
                    "res": (res, res),
                    "kind": "ndsm",
                },
                data={"kind": "ndsm"},
                sources=[source],
                notes=[
                    "nDSM = last-return DSM minus DTM (EA LiDAR composites, mixed survey epochs); "
                    f"resampled to a square {res:g} m grid in {aoi.epsg}; negatives clipped to 0.",
                    f"mean_height_m is the mean over cells taller than {BUILDING_LIKE_MIN_M} m.",
                ],
            ),
            aoi,
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        """Coverage over the cells inside the square; mean over cells above BUILDING_LIKE_MIN_M.

        Corner cells of the bounding box belong to the neighbours, not missing LiDAR.
        """
        arr = np.asarray(result.raster["array"], dtype=float)
        inside = inside_aoi(arr.shape, result.raster["transform"], aoi)
        finite = np.isfinite(arr) & inside
        n_inside = int(inside.sum())
        coverage = float(finite.sum()) / n_inside if n_inside else 0.0
        tall = arr[finite & (arr > BUILDING_LIKE_MIN_M)]
        data = {
            **(result.data or {}),
            "mean_height_m": float(tall.mean()) if tall.size else None,
            "kind": "ndsm",
        }
        return replace(result, data=data, coverage=coverage, degraded=coverage < 0.5, findings=[])


REGISTRY.register(EaLidarBuildingHeightProvider())
