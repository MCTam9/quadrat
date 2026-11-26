"""Serialise a loaded site's layers to one zip and back.

Layout of the zip:

- `manifest.json`: format version, the outer AOI and per-layer metadata (provider,
  coverage, degraded, notes, findings, sources, raster description).
- `<layer>/gdf.pkl`: vector layers as pickled GeoDataFrames (CRS kept; shapely 2 pickles
  geometries as WKB). Raw OSM tags make mixed-type columns that Parquet cannot hold, and this
  keeps pyarrow out of the hosted API.
- `<layer>/raster.tif`: raster layers as DEFLATE GeoTIFF. The true-north "inside" mask is
  derived from the raster's square, so it is rebuilt rather than stored.
- `<layer>/data.pkl`: `LayerResult.data` (street graph, climate series, summaries). Pickle
  is lossless for the graph and numpy series; we only ever read blobs we wrote ourselves
  into a private store.

A version bump makes old snapshots unreadable on purpose: `restore` raises and the caller
treats it as a miss.
"""

from __future__ import annotations

import io
import json
import pickle
import zipfile
from typing import Any

import numpy as np
from affine import Affine
from pyproj import CRS
from shapely import wkb

from .aoi import AOI
from .raster import SiteRaster
from .types import LayerResult, Source

FORMAT_VERSION = 2


def _aoi_to_dict(aoi: AOI) -> dict[str, Any]:
    return {
        "name": aoi.name,
        "wkb": aoi.geometry.wkb_hex,
        "crs": aoi.crs.to_wkt(),
        "centroid_lonlat": list(aoi.centroid_lonlat),
        "radius_m": aoi.radius_m,
        "meta": aoi.meta,
    }


def _aoi_from_dict(d: dict[str, Any]) -> AOI:
    return AOI(
        name=d["name"],
        geometry=wkb.loads(d["wkb"], hex=True),
        crs=CRS.from_wkt(d["crs"]),
        centroid_lonlat=(d["centroid_lonlat"][0], d["centroid_lonlat"][1]),
        radius_m=d["radius_m"],
        meta=d["meta"],
    )


def _raster_bytes(r: SiteRaster) -> tuple[bytes, dict[str, Any]]:
    from rasterio.io import MemoryFile

    arr = np.asarray(r.array)
    stored = arr.astype(np.uint8) if arr.dtype == bool else arr
    bands = stored[np.newaxis] if stored.ndim == 2 else np.moveaxis(stored, -1, 0)
    predictor = 3 if np.issubdtype(bands.dtype, np.floating) else 2
    profile = {
        "driver": "GTiff",
        "height": bands.shape[1],
        "width": bands.shape[2],
        "count": bands.shape[0],
        "dtype": bands.dtype,
        "transform": r.transform,
        "compress": "DEFLATE",
        "predictor": predictor,
        "tiled": False,
    }
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(bands)
        data = mem.read()
    meta = {
        "dtype": str(arr.dtype),
        "ndim": arr.ndim,
        "transform": list(r.transform)[:6],
        "crs": CRS.from_user_input(r.crs).to_wkt(),
        "square": _aoi_to_dict(r.square),
        "nodata": None if r.nodata is None else float(r.nodata),
        "nodata_is_int": isinstance(r.nodata, (int, np.integer)),
        "kind": r.kind,
    }
    return data, meta


def _raster_from(data: bytes, m: dict[str, Any]) -> SiteRaster:
    from rasterio.io import MemoryFile

    with MemoryFile(data) as mem, mem.open() as src:
        bands = src.read()
    arr = bands[0] if m["ndim"] == 2 else np.moveaxis(bands, 0, -1)
    arr = np.ascontiguousarray(arr.astype(np.dtype(m["dtype"])))
    nodata = m["nodata"]
    if nodata is not None and m["nodata_is_int"]:
        nodata = int(nodata)
    return SiteRaster(
        array=arr,
        transform=Affine(*m["transform"]),
        crs=CRS.from_wkt(m["crs"]),
        square=_aoi_from_dict(m["square"]),
        nodata=nodata,
        kind=m["kind"],
    )


def dump(outer: AOI, layers: dict[str, LayerResult]) -> bytes:
    manifest: dict[str, Any] = {"version": FORMAT_VERSION, "outer": _aoi_to_dict(outer), "layers": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, res in layers.items():
            entry: dict[str, Any] = {
                "name": name,
                "layer": res.layer,
                "provider": res.provider,
                "coverage": res.coverage,
                "degraded": bool(res.degraded),
                "notes": list(res.notes),
                "findings": list(res.findings),
                "sources": [s.to_dict() for s in res.sources],
                "gdf": None,
                "raster": None,
                "has_data": res.data is not None,
            }
            if res.gdf is not None:
                zf.writestr(f"{name}/gdf.pkl", pickle.dumps(res.gdf, protocol=5))
                entry["gdf"] = "gdf.pkl"
            if res.raster is not None:
                payload, entry["raster"] = _raster_bytes(res.raster)
                zf.writestr(f"{name}/raster.tif", payload, compress_type=zipfile.ZIP_STORED)
            if res.data is not None:
                zf.writestr(f"{name}/data.pkl", pickle.dumps(res.data, protocol=5))
            manifest["layers"].append(entry)
        zf.writestr("manifest.json", json.dumps(manifest))
    return buf.getvalue()


def load(data: bytes) -> tuple[AOI, dict[str, LayerResult]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("version") != FORMAT_VERSION:
            raise ValueError(f"unsupported snapshot version {manifest.get('version')!r}")
        outer = _aoi_from_dict(manifest["outer"])
        layers: dict[str, LayerResult] = {}
        for e in manifest["layers"]:
            name = e["name"]
            layers[name] = LayerResult(
                layer=e["layer"],
                provider=e["provider"],
                gdf=pickle.loads(zf.read(f"{name}/gdf.pkl")) if e["gdf"] else None,
                raster=_raster_from(zf.read(f"{name}/raster.tif"), e["raster"]) if e["raster"] else None,
                data=pickle.loads(zf.read(f"{name}/data.pkl")) if e["has_data"] else None,
                sources=[Source(**s) for s in e["sources"]],
                coverage=e["coverage"],
                degraded=e["degraded"],
                notes=e["notes"],
                findings=e["findings"],
            )
    return outer, layers
