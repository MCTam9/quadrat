"""Copernicus GLO-30 DSM terrain provider.

Reads only the AOI window from the public AWS COGs (HTTP range requests via
GDAL's `/vsicurl/`, never a whole 3600x3600 tile) and reprojects that window to
a square metre grid in the AOI CRS *before* any slope/aspect computation is
attempted downstream. GLO-30 is a digital SURFACE model: rooftops and canopy
are baked into the elevation, so it is not a substitute for a bare-earth DTM.
"""

from __future__ import annotations

import math

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.merge import merge as rio_merge
from rasterio.windows import from_bounds

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._terrain_grid import elevation_summary, reproject_merged_to_square_grid

BUCKET_HTTPS = "https://copernicus-dem-30m.s3.amazonaws.com"
RESOLUTION_M = 30.0
# Padding, in degrees, applied to a tile's boundless read so a merge across
# adjacent tiles has no gap at the seam introduced by float rounding.
_PAD_DEG = 0.01


def _tile_url(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    name = f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"
    return f"{BUCKET_HTTPS}/{name}/{name}.tif"


class CopernicusTerrainProvider(Provider):
    """1-degree GLO-30 DSM tiles, windowed, merged and reprojected to metres."""

    name = "copernicus_terrain"
    layer = "terrain"
    licence = "COPDEM ESA licence (free, attribution)"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:  # noqa: ANN001
        return True

    def fetch(self, aoi, cache) -> LayerResult:  # noqa: ANN001
        w, s, e, n = aoi.bbox_wgs84
        lat0, lat1 = math.floor(s), math.floor(n)
        lon0, lon1 = math.floor(w), math.floor(e)

        memfiles = []
        datasets = []
        src_crs = None
        try:
            for lat in range(lat0, lat1 + 1):
                for lon in range(lon0, lon1 + 1):
                    url = _tile_url(lat, lon)
                    key = cache.key(
                        "copernicus-terrain", url, round(w, 5), round(s, 5), round(e, 5), round(n, 5)
                    )
                    blob, _meta = cache.get_bytes(key, ".tif", self._make_producer(url, w, s, e, n, lat, lon))
                    memfile = MemoryFile(blob)
                    memfiles.append(memfile)
                    ds = memfile.open()
                    datasets.append(ds)
                    src_crs = ds.crs

            if not datasets:
                raise RuntimeError("copernicus_terrain: no tiles intersect AOI")

            merged_arr, merged_transform = rio_merge(datasets)
            merged_arr = merged_arr[0].astype(np.float32)
        finally:
            for ds in datasets:
                ds.close()
            for mf in memfiles:
                mf.close()

        dst_arr, dst_transform = reproject_merged_to_square_grid(
            merged_arr, merged_transform, src_crs, aoi, RESOLUTION_M
        )

        source = Source(
            name="Copernicus DEM GLO-30 (ESA/Airbus DS, AWS Open Data)",
            url=BUCKET_HTTPS,
            licence=self.licence,
            licence_url=f"{BUCKET_HTTPS}/readme.html",
            note=(
                "GLO-30 is a digital SURFACE model: elevations include rooftops, walls and "
                "canopy, not bare earth. Read as a windowed range request per 1x1 degree tile, "
                "merged, then reprojected to a square metre grid before any slope computation."
            ),
            commercial_ok=True,
        )

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            raster={
                "array": dst_arr,
                "transform": dst_transform,
                "crs": aoi.crs,
                "nodata": float("nan"),
                "res": (RESOLUTION_M, RESOLUTION_M),
            },
            data={
                "terrain_model": "DSM",
                **elevation_summary(dst_arr),
            },
            sources=[source],
            coverage=1.0,
            degraded=False,
            notes=[
                "Copernicus GLO-30 is a DSM (surface model), not a bare-earth DTM: rooftops "
                "and canopy inflate elevation and any slope derived from it.",
                f"Reprojected to {aoi.epsg} on a square {RESOLUTION_M:.0f} m grid "
                "(rasterio.warp.reproject, Resampling.bilinear) before any slope computation.",
            ],
        )

    @staticmethod
    def _make_producer(url: str, w: float, s: float, e: float, n: float, lat: int, lon: int):
        def _producer() -> tuple[bytes, dict]:
            remote = f"/vsicurl/{url}"
            with rasterio.open(remote) as src:
                win = from_bounds(
                    max(w, lon) - _PAD_DEG,
                    max(s, lat) - _PAD_DEG,
                    min(e, lon + 1) + _PAD_DEG,
                    min(n, lat + 1) + _PAD_DEG,
                    transform=src.transform,
                ).round_lengths().round_offsets()
                arr = src.read(1, window=win, boundless=True, fill_value=0.0)
                transform = src.window_transform(win)
                profile = src.profile.copy()
                profile.update(height=arr.shape[0], width=arr.shape[1], transform=transform, count=1)
                with MemoryFile() as mem:
                    with mem.open(**profile) as dst:
                        dst.write(arr, 1)
                    data = mem.read()
            return data, {"url": url, "licence": "COPDEM ESA licence (free, attribution)"}

        return _producer


REGISTRY.register(CopernicusTerrainProvider())
