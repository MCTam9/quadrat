"""ESA WorldCover 10 m v200 (2021) land-cover provider.

Fills the honest gap left by OSM `landuse` tagging, which is dense in Western
Europe and sparse across Central Asia, the Gulf and much of the Global South.
Read as a windowed range request per 3x3 degree tile from the public,
anonymous-access AWS bucket, then reprojected to the AOI metric CRS with
nearest-neighbour resampling — the values are categorical class codes, and
bilinear interpolation across class codes produces meaningless in-between
numbers.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import rasterio
from affine import Affine
from rasterio.io import MemoryFile
from rasterio.merge import merge as rio_merge
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._terrain_grid import inside_aoi

BUCKET_HTTPS = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
TILE_SIZE_DEG = 3
RESOLUTION_M = 10.0
_PAD_DEG = 0.01

# Official ESA WorldCover v200 class map and palette.
CLASSES: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

CLASS_COLOURS: dict[int, str] = {
    10: "#006400",
    20: "#ffbb22",
    30: "#ffff4c",
    40: "#f096ff",
    50: "#fa0000",
    60: "#b4b4b4",
    70: "#f0f0f0",
    80: "#0064c8",
    90: "#0096a0",
    95: "#00cf75",
    100: "#fae6a0",
}


def _tile_origin(lat: float, lon: float) -> tuple[int, int]:
    return (
        int(math.floor(lat / TILE_SIZE_DEG) * TILE_SIZE_DEG),
        int(math.floor(lon / TILE_SIZE_DEG) * TILE_SIZE_DEG),
    )


def _tile_url(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    name = f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat):02d}{ew}{abs(lon):03d}_Map"
    return f"{BUCKET_HTTPS}/v200/2021/map/{name}.tif"


class WorldCoverProvider(Provider):
    """3x3 degree WorldCover tiles, windowed, merged and reprojected to metres."""

    name = "esa_worldcover"
    layer = "landcover"
    licence = "CC BY 4.0"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        w, s, e, n = aoi.bbox_wgs84
        lat0, lon0 = _tile_origin(s, w)
        lat1, lon1 = _tile_origin(n, e)

        memfiles = []
        datasets = []
        src_crs = None
        try:
            for lat in range(lat0, lat1 + 1, TILE_SIZE_DEG):
                for lon in range(lon0, lon1 + 1, TILE_SIZE_DEG):
                    url = _tile_url(lat, lon)
                    key = cache.key("esa-worldcover", url, round(w, 5), round(s, 5), round(e, 5), round(n, 5))
                    producer = self._make_producer(url, w, s, e, n, lat, lon)
                    blob, _meta = cache.get_bytes(key, ".tif", producer)
                    memfile = MemoryFile(blob)
                    memfiles.append(memfile)
                    ds = memfile.open()
                    datasets.append(ds)
                    src_crs = ds.crs

            if not datasets:
                raise RuntimeError("esa_worldcover: no tiles intersect AOI")

            merged_arr, merged_transform = rio_merge(datasets)
            merged_arr = merged_arr[0]
        finally:
            for ds in datasets:
                ds.close()
            for mf in memfiles:
                mf.close()

        minx, miny, maxx, maxy = aoi.bounds_metric
        width = max(1, math.ceil((maxx - minx) / RESOLUTION_M))
        height = max(1, math.ceil((maxy - miny) / RESOLUTION_M))
        dst_transform = Affine(RESOLUTION_M, 0.0, minx, 0.0, -RESOLUTION_M, maxy)
        dst_arr = np.zeros((height, width), dtype=np.uint8)

        reproject(
            source=merged_arr,
            destination=dst_arr,
            src_transform=merged_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=aoi.crs,
            resampling=Resampling.nearest,
            src_nodata=0,
            dst_nodata=0,
        )

        inside = inside_aoi(dst_arr.shape, dst_transform, aoi)
        dst_arr[~inside] = 0

        source = Source(
            name="ESA WorldCover 10m v200 (2021)",
            url=BUCKET_HTTPS,
            licence=self.licence,
            licence_url="https://creativecommons.org/licenses/by/4.0/",
            note=(
                "Windowed read per 3x3 degree tile from the public anonymous-access AWS "
                "bucket, merged, reprojected with nearest-neighbour (categorical class codes)."
            ),
            commercial_ok=True,
        )

        return self.summarise(
            LayerResult(
                layer=self.layer,
                provider=self.name,
                raster={
                    "array": dst_arr,
                    "transform": dst_transform,
                    "crs": aoi.crs,
                    "nodata": 0,
                    "res": (RESOLUTION_M, RESOLUTION_M),
                },
                data={
                    "class_colours": {CLASSES[k]: v for k, v in CLASS_COLOURS.items()},
                },
                sources=[source],
                notes=[
                    "Fills the gap in OSM landuse coverage across regions (Central Asia, the Gulf, "
                    "much of the Global South) where OSM landuse tagging is sparse or absent.",
                ],
            ),
            aoi,
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        """Class fractions over the cells inside the square; coverage = 1 - unclassified."""
        arr = np.asarray(result.raster["array"])
        inside = inside_aoi(arr.shape, result.raster["transform"], aoi)
        total = max(int(inside.sum()), 1)
        fractions: dict[str, float] = {}
        for code, cls_name in CLASSES.items():
            count = int(np.count_nonzero((arr == code) & inside))
            if count:
                fractions[cls_name] = count / total
        unclassified = int(np.count_nonzero((arr == 0) & inside)) / total
        if unclassified:
            fractions["Unclassified/no data"] = unclassified
        data = {**(result.data or {}), "class_fractions": fractions}
        return replace(result, data=data, coverage=1.0 - unclassified, degraded=False, findings=[])

    @staticmethod
    def _make_producer(url: str, w: float, s: float, e: float, n: float, lat: int, lon: int):
        def _producer() -> tuple[bytes, dict]:
            remote = f"/vsicurl/{url}"
            with rasterio.open(remote) as src:
                win = (
                    from_bounds(
                        max(w, lon) - _PAD_DEG,
                        max(s, lat) - _PAD_DEG,
                        min(e, lon + TILE_SIZE_DEG) + _PAD_DEG,
                        min(n, lat + TILE_SIZE_DEG) + _PAD_DEG,
                        transform=src.transform,
                    )
                    .round_lengths()
                    .round_offsets()
                )
                arr = src.read(1, window=win, boundless=True, fill_value=0)
                transform = src.window_transform(win)
                profile = src.profile.copy()
                profile.update(height=arr.shape[0], width=arr.shape[1], transform=transform, count=1)
                with MemoryFile() as mem:
                    with mem.open(**profile) as dst:
                        dst.write(arr, 1)
                    data = mem.read()
            return data, {"url": url, "licence": "CC BY 4.0"}

        return _producer


REGISTRY.register(WorldCoverProvider())
