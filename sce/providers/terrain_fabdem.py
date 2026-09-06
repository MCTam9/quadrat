"""FABDEM v1.2 bare-earth terrain provider. Opt-in only, non-commercial.

FABDEM (Forest And Buildings removed Copernicus DEM, University of Bristol /
Fathom) starts from Copernicus GLO-30 and machine-learns forest canopy and
building height back out of it, so it is a true bare-earth DTM rather than the
surface model `terrain_copernicus` returns. That is the entire reason to want
it: slope computed on rooftops and tree crowns is not the slope of the ground.

LICENCE: FABDEM v1.2 is **CC BY-NC-SA 4.0** - non-commercial, share-alike,
with commercial use requiring a separate arrangement with fathom.global. This
provider therefore sets `commercial_ok = False`, and the registry
(`sce/registry.py`) skips non-commercial providers unless the caller passes
`allow_non_commercial=True`; `sce/cli.py` only does that when `--dtm fabdem`
is explicitly given, and prints its own warning at that point too.
`sce/report/sheet.py` prints a bold "NON-COMMERCIAL LICENCE IN USE" line in
the title block whenever any source on the sheet declares `commercial_ok`
False, so the licence is never buried in a footnote.

RETRIEVABILITY, INVESTIGATED (2026-09): FABDEM is not published as windowed
COGs the way Copernicus GLO-30 is on AWS. It is distributed from
data.bris.ac.uk as ~250 zip archives, each a 10x10 degree block of zipped
1x1 degree GeoTIFFs (tile naming e.g. `N51E005_FABDEM_V1-2.tif`), and single
10-degree zips run tens to hundreds of megabytes each even where the block is
mostly ocean. A guessed direct-file URL on that pattern does return the bytes
over plain HTTPS with no login prompt or cookie challenge, so there is no
*hard* authentication wall in front of the raw files - but there is no stable,
documented, versioned API either: the resource IDs on the dataset's own
catalogue page are opaque and not derivable from a tile name, so a scraper
would be depending on an undocumented URL convention that Bristol's hosting
could change at any time, and it would have to pull a whole 10-degree
zip - unlike Copernicus's per-tile ranged COG read - to get a handful of 1
degree tiles for one AOI. Given the licence also explicitly asks users to
route through its own catalogue/attribution page rather than being scraped,
this provider does not attempt automated retrieval. It reads already-unzipped
`N{lat:02d}{lat_ns}E{lon:03d}{lon_ew}_FABDEM_V1-2.tif` tiles from a local
directory instead.

Point `SCE_FABDEM_DIR` at a directory containing those GeoTIFFs (extracted
from the zips you download by hand from
https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn after reading
and accepting the CC BY-NC-SA 4.0 terms there). `available()` returns False,
cheaply and with no network access, whenever that variable is unset or the
directory does not exist, so the registry falls through to the Copernicus DSM
without the caller having to do anything. `fetch()` only runs once the
registry (or an explicit `--dtm fabdem` override) has already decided this
provider is in play, and raises a clear, actionable error if the directory
exists but is missing tiles for this AOI, rather than silently returning
degraded data.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._terrain_grid import elevation_summary, reproject_merged_to_square_grid

RESOLUTION_M = 30.0
LICENCE = "CC BY-NC-SA 4.0 (Bristol/Fathom FABDEM v1.2)"
LICENCE_URL = "https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn"

DOWNLOAD_HELP = (
    "FABDEM tiles are not fetched automatically (see sce/providers/terrain_fabdem.py "
    "module docstring for why). To use --dtm fabdem: "
    "1) read and accept the CC BY-NC-SA 4.0 terms at "
    f"{LICENCE_URL} ; "
    "2) download the 10x10 degree zip(s) covering your AOI and unzip the 1x1 degree "
    "*_FABDEM_V1-2.tif tiles you need into one directory; "
    "3) set SCE_FABDEM_DIR to that directory. "
    "The licence is non-commercial (share-alike); commercial use needs a separate "
    "arrangement with fathom.global."
)


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}_FABDEM_V1-2.tif"


def _fabdem_dir() -> Path | None:
    raw = os.environ.get("SCE_FABDEM_DIR")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


class FabdemTerrainProvider(Provider):
    """Bare-earth DTM read from local FABDEM v1.2 tiles. Non-commercial only."""

    name = "fabdem"
    layer = "terrain"
    licence = LICENCE
    rank = 20
    commercial_ok = False

    def available(self, aoi) -> bool:
        # Cheap, no network: only true when the user has actually supplied
        # tiles, so the registry falls through to Copernicus cleanly otherwise.
        return _fabdem_dir() is not None

    def fetch(self, aoi, cache) -> LayerResult:
        tile_dir = _fabdem_dir()
        if tile_dir is None:
            raise RuntimeError(f"fabdem: SCE_FABDEM_DIR is not set or not a directory. {DOWNLOAD_HELP}")

        w, s, e, n = aoi.bbox_wgs84
        lat0, lat1 = math.floor(s), math.floor(n)
        lon0, lon1 = math.floor(w), math.floor(e)

        found: list[Path] = []
        missing: list[str] = []
        for lat in range(lat0, lat1 + 1):
            for lon in range(lon0, lon1 + 1):
                name = _tile_name(lat, lon)
                p = tile_dir / name
                if p.exists():
                    found.append(p)
                else:
                    missing.append(name)

        if not found:
            raise RuntimeError(
                f"fabdem: no tiles for this AOI found in {tile_dir}. "
                f"Expected: {', '.join(missing)}. {DOWNLOAD_HELP}"
            )

        datasets = []
        src_crs = None
        try:
            for p in found:
                ds = rasterio.open(p)
                datasets.append(ds)
                src_crs = ds.crs

            merged_arr, merged_transform = rio_merge(datasets)
            merged_arr = merged_arr[0].astype(np.float32)
        finally:
            for ds in datasets:
                ds.close()

        dst_arr, dst_transform = reproject_merged_to_square_grid(
            merged_arr, merged_transform, src_crs, aoi, RESOLUTION_M
        )

        source = Source(
            name="FABDEM v1.2 (Univ. of Bristol / Fathom)",
            url=LICENCE_URL,
            licence=LICENCE,
            licence_url=LICENCE_URL,
            note=(
                "Bare-earth DTM: Copernicus GLO-30 with forest canopy and building height "
                "machine-learned out. Read from local tiles supplied via SCE_FABDEM_DIR (no "
                "automated download, see module docstring), merged, then reprojected to a "
                "square metre grid before any slope computation. NON-COMMERCIAL LICENCE."
            ),
            commercial_ok=False,
        )

        notes = [
            "FABDEM v1.2 is bare earth (DTM): canopy and building height are removed, unlike "
            "the Copernicus GLO-30 DSM default.",
            f"Reprojected to {aoi.epsg} on a square {RESOLUTION_M:.0f} m grid "
            "(rasterio.warp.reproject, Resampling.bilinear) before any slope computation.",
            "CC BY-NC-SA 4.0: non-commercial use only.",
        ]
        if missing:
            notes.append(f"AOI partially covered: missing tiles {', '.join(missing)}.")

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
                "terrain_model": "DTM",
                **elevation_summary(dst_arr),
            },
            sources=[source],
            coverage=1.0 if not missing else max(0.0, 1.0 - len(missing) / (len(missing) + len(found))),
            degraded=bool(missing),
            notes=notes,
        )


REGISTRY.register(FabdemTerrainProvider())
