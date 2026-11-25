"""Private site-picker backend: Clerk-authenticated FastAPI over the sce pipeline.

Flow: `/api/load` fetches a padded 3 km square once (slow, streamed as SSE) and
keeps it in a small in-process LRU; `/api/analyse` and `/api/preview` then
clip whatever smaller square the user drags inside it (fast); `/api/export`
bundles the chosen formats into a zip.

The LRU is per process. On a serverless host a cold instance will not have it,
which is why the clip endpoints answer 409 `{"error": "reload"}` and the
frontend re-runs `/api/load`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import zipfile
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

# Must precede the first `sce.cache` import, which reads it at import time.
os.environ.setdefault("SCE_CACHE", "/tmp/sce-cache")

import jwt
import numpy as np
import shapely
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from shapely.geometry import mapping
from starlette.background import BackgroundTask

import sce
from sce import pipeline
from sce.aoi import AOI
from sce.cache import Cache
from sce.clip import ClipOutsideError, clip_layers, contains
from sce.export.dossier import _dedup_sources
from sce.types import LayerResult

log = logging.getLogger("sce.api")

# The padded fetch is sized to the square the user starts with, plus room to
# drag. A fixed 3 km x 3 km fetch was too heavy for the public Overpass servers.
PADDED_HALF_WIDTH_M = 1500.0  # upper bound
PADDED_MIN_HALF_WIDTH_M = 750.0
PADDED_MARGIN_M = 500.0
MIN_HALF_WIDTH_M = 50.0
MAX_HALF_WIDTH_M = 1000.0
MAX_PREVIEW_FEATURES = 20000
PING_SECONDS = 10.0
CHUNK_BYTES = 64 * 1024

# ---------------------------------------------------------------- auth


def _auth_disabled() -> bool:
    return os.environ.get("SCE_AUTH_DISABLED") == "1"


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(os.environ["CLERK_JWKS_URL"], cache_keys=True)


def _unauthorised(msg: str) -> HTTPException:
    return HTTPException(status_code=401, detail=msg)


def require_auth(request: Request) -> None:
    """Verify a Clerk session JWT (RS256). Sync, so the JWKS fetch runs in a thread."""
    if _auth_disabled():
        return
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorised("missing bearer token")
    try:
        key = _jwks_client().get_signing_key_from_jwt(token.strip()).key
        issuer = os.environ.get("CLERK_ISSUER") or None
        claims = jwt.decode(
            token.strip(),
            key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "require": ["exp"],
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iss": issuer is not None,
                "verify_aud": False,
            },
        )
    except jwt.PyJWTError as exc:
        log.info("auth rejected: %s", exc)
        raise _unauthorised("invalid token") from exc
    except KeyError as exc:
        log.error("auth misconfigured: %s not set", exc)
        raise _unauthorised("auth not configured") from exc
    parties = [p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",")]
    parties = [p for p in parties if p]
    if parties and claims.get("azp") not in parties:
        log.info("auth rejected: azp %r not authorised", claims.get("azp"))
        raise _unauthorised("unauthorised party")


# ---------------------------------------------------------------- site store


class _SiteStore:
    """Thread-safe LRU of (outer AOI, layers) keyed by site id."""

    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self._items: OrderedDict[str, tuple[AOI, dict[str, LayerResult]]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key: str, value: tuple[AOI, dict[str, LayerResult]]) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def get(self, key: str | None) -> tuple[AOI, dict[str, LayerResult]] | None:
        if key is None:
            return None
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


SITES = _SiteStore(8)


def site_key(lon: float, lat: float, padded_half_width_m: float = PADDED_HALF_WIDTH_M) -> str:
    return f"{lon:.5f},{lat:.5f},{padded_half_width_m:.0f}"


def padded_half_width(half_width_m: float | None) -> float:
    """Padded fetch half-width for a square of this half-width (None -> the maximum)."""
    if half_width_m is None:
        return PADDED_HALF_WIDTH_M
    return min(PADDED_HALF_WIDTH_M, max(PADDED_MIN_HALF_WIDTH_M, half_width_m + PADDED_MARGIN_M))


# ---------------------------------------------------------------- models


class Point(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class LoadRequest(Point):
    half_width_m: float | None = Field(default=None, ge=MIN_HALF_WIDTH_M, le=MAX_HALF_WIDTH_M)


class SiteRequest(BaseModel):
    site_id: str


class SquareRequest(Point):
    site_id: str
    half_width_m: float = Field(ge=MIN_HALF_WIDTH_M, le=MAX_HALF_WIDTH_M)


class ExportRequest(Point):
    site_id: str | None = None
    half_width_m: float = Field(ge=MIN_HALF_WIDTH_M, le=MAX_HALF_WIDTH_M)
    formats: list[str] = Field(default_factory=list)
    report: bool = True


# ---------------------------------------------------------------- helpers


def _json_safe(obj: Any) -> Any:
    """Recursively reduce to JSON types; unserialisable values (graphs, arrays) are dropped."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, np.generic):
        return _json_safe(obj.item())
    if isinstance(obj, (int,)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            safe = _json_safe(v)
            if safe is not _DROP:
                out[str(k)] = safe
        return out
    if isinstance(obj, (list, tuple, set)):
        return [s for s in (_json_safe(v) for v in obj) if s is not _DROP]
    return _DROP


_DROP = object()


def _clean(obj: Any) -> Any:
    safe = _json_safe(obj)
    return None if safe is _DROP else safe


def _square_geojson(aoi: AOI) -> dict[str, Any]:
    geom = shapely.transform(aoi.geometry_wgs84, lambda c: np.round(c, 6))
    return dict(mapping(geom))


def _bbox(aoi: AOI) -> list[float]:
    return [round(v, 6) for v in aoi.bbox_wgs84]


def _cached_inner(req: SquareRequest) -> tuple[AOI, AOI, dict[str, LayerResult]]:
    """(outer, inner, outer layers) or a 409 telling the client to reload."""
    cached = SITES.get(req.site_id)
    if cached is None:
        raise HTTPException(status_code=409, detail="reload")
    outer, layers = cached
    inner = AOI.from_point(req.lon, req.lat, req.half_width_m, name="site", crs=outer.crs)
    if not contains(outer, inner):
        raise HTTPException(status_code=409, detail="reload")
    return outer, inner, layers


def _rounded(gdf: Any) -> Any:
    geoms = shapely.transform(gdf.geometry.values, lambda c: np.round(c, 6))
    return gdf.set_geometry(geoms)


def _feature_collection(gdf: Any, props: Any) -> dict[str, Any]:
    features = []
    if gdf is not None and len(gdf):
        gdf = _rounded(gdf.to_crs(4326))
        # Plain dicts, not itertuples: namedtuples rename `class` and `building:levels`.
        rows = gdf.drop(columns=gdf.geometry.name).to_dict("records")
        for geom, row in zip(gdf.geometry, rows, strict=True):
            if geom is None or geom.is_empty:
                continue
            features.append({"type": "Feature", "geometry": mapping(geom), "properties": props(row)})
            if len(features) >= MAX_PREVIEW_FEATURES:
                break
    return {"type": "FeatureCollection", "features": features}


def _building_props(row: Any) -> dict[str, Any]:
    d = row
    h = d.get("height_m")
    try:
        h = float(h)
    except (TypeError, ValueError):
        h = None
    if h is not None and not math.isfinite(h):
        h = None
    src = d.get("height_source", "")
    levels = d.get("building:levels")
    try:
        levels = float(levels) if levels is not None else None
    except (TypeError, ValueError):
        levels = None
    if levels is not None and not math.isfinite(levels):
        levels = None
    return {
        "height_m": h,
        "height_source": src if isinstance(src, str) else "",
        "building": _str_or_none(d.get("building")),
        "levels": levels,
        "use": _str_or_none(d.get("use")),
        "use_source": _str_or_none(d.get("use_source")),
    }


def _street_props(row: Any) -> dict[str, Any]:
    hw = row.get("highway", "")
    if isinstance(hw, (list, tuple)):
        hw = hw[0] if hw else ""
    return {"highway": hw if isinstance(hw, str) else ""}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------- app

CORS_ORIGINS = [o.strip() for o in os.environ.get("SCE_CORS_ORIGINS", "").split(",") if o.strip()]


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    if _auth_disabled():
        log.warning("SCE_AUTH_DISABLED=1: authentication is OFF. Local development only.")
    yield


app = FastAPI(title="Site Context Report API", lifespan=_lifespan, docs_url=None, redoc_url=None)
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    return JSONResponse({"error": f"invalid {loc}: {first.get('msg', 'bad request')}"}, status_code=422)


@app.exception_handler(Exception)
async def _internal_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse({"error": "internal error"}, status_code=500)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": sce.__version__}


api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@api.post("/load")
async def load(req: LoadRequest) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def emit(event: str, data: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    padded = padded_half_width(req.half_width_m)

    def work() -> None:
        try:
            outer = AOI.from_point(req.lon, req.lat, padded, name="padded")

            def on_layer(name: str, result: LayerResult | None) -> None:
                emit(
                    "layer",
                    {
                        "layer": name,
                        "provider": result.provider if result else None,
                        "features": 0 if result is None or result.gdf is None else len(result.gdf),
                        "coverage": _clean(result.coverage) if result else None,
                        "ok": result is not None,
                    },
                )

            layers = pipeline.fetch_layers(outer, Cache(), on_layer=on_layer)
            if not layers:
                raise RuntimeError("no data available for this location")
            sid = site_key(req.lon, req.lat, padded)
            SITES.put(sid, (outer, layers))
            emit(
                "ready",
                {
                    "site_id": sid,
                    "epsg": outer.epsg,
                    "centre": [req.lon, req.lat],
                    "padded_half_width_m": padded,
                    "bbox_wgs84": _bbox(outer),
                },
            )
        except Exception:
            log.exception("load failed")
            emit("error", {"error": "could not load data for this location"})

    async def stream() -> AsyncIterator[str]:
        thread = threading.Thread(target=work, name="sce-load", daemon=True)
        thread.start()
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), PING_SECONDS)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _sse(event, data)
            if event in ("ready", "error"):
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@api.post("/analyse")
def analyse(req: SquareRequest) -> dict[str, Any]:
    outer, inner, layers = _cached_inner(req)
    try:
        clipped = clip_layers(layers, outer, inner)
    except ClipOutsideError as exc:
        raise HTTPException(status_code=409, detail="reload") from exc
    metrics, assessment = pipeline.analyse(clipped, inner)
    return {
        "aoi": {**_clean(inner.provenance()), "square": _square_geojson(inner)},
        "metrics": _clean(metrics),
        "assessment": _clean(assessment),
        "layers": {
            name: {
                "provider": r.provider,
                "coverage": _clean(r.coverage),
                "degraded": bool(r.degraded),
                "notes": _clean(r.notes),
            }
            for name, r in sorted(clipped.items())
        },
    }


@api.post("/preview")
def preview(req: SquareRequest) -> dict[str, Any]:
    outer, inner, layers = _cached_inner(req)
    b, s = layers.get("buildings"), layers.get("streets")
    lu, cons = layers.get("landuse"), layers.get("constraints")
    contours, interval = _contours(layers.get("terrain"), outer, inner)
    return {
        "square": {"type": "Feature", "geometry": _square_geojson(inner), "properties": {}},
        "buildings": _feature_collection(_buildings_with_use(b, layers, inner), _building_props),
        "streets": _feature_collection(inner.clip(s.gdf) if s is not None else None, _street_props),
        "landuse": _feature_collection(
            inner.clip(lu.gdf) if lu is not None and lu.gdf is not None else None, _landuse_props
        ),
        "contours": _feature_collection(contours, lambda row: {"elevation_m": row["elevation_m"]}),
        "contour_interval_m": interval,
        "constraints": _feature_collection(
            inner.clip(cons.gdf) if cons is not None and cons.gdf is not None else None, _constraint_props
        ),
    }


def _buildings_with_use(b: LayerResult | None, layers: dict[str, LayerResult], inner: AOI) -> Any:
    """Clipped buildings with `use`/`use_source` (tagged or inferred, see sce.building_use)."""
    if b is None or b.gdf is None:
        return None
    from sce.building_use import infer_building_use

    gdf = inner.clip(b.gdf)
    if not len(gdf):
        return gdf
    am, lu = layers.get("amenities"), layers.get("landuse")
    uses = infer_building_use(
        gdf,
        inner.clip(am.gdf) if am is not None and am.gdf is not None else None,
        inner.clip(lu.gdf) if lu is not None and lu.gdf is not None else None,
    )
    return gdf.assign(use=uses["use"], use_source=uses["use_source"])


def _contours(terrain: LayerResult | None, outer: AOI, inner: AOI) -> tuple[Any, float | None]:
    """Contour lines for the inner square, at the same interval the CAD exports use."""
    if terrain is None or terrain.raster is None:
        return None, None
    import geopandas as gpd
    from shapely.geometry import LineString

    from sce.export._contours import choose_contour_interval, terrain_contours

    clipped = clip_layers({"terrain": terrain}, outer, inner)["terrain"]
    arr = np.asarray(clipped.raster["array"], dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None, None
    lines = terrain_contours(clipped)
    gdf = gpd.GeoDataFrame(
        {"elevation_m": [round(z, 1) for z, _ in lines]},
        geometry=[LineString(pts) for _, pts in lines],
        crs=inner.crs,
    )
    return inner.clip(gdf), choose_contour_interval(float(finite.min()), float(finite.max()))


def _str_or_none(v: Any) -> str | None:
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return str(v)


def _landuse_props(row: Any) -> dict[str, Any]:
    from sce.metrics.landuse import _normalise_class

    return {"class": _normalise_class(_str_or_none(row.get("class")))}


def _constraint_props(row: Any) -> dict[str, Any]:
    d = row
    return {"dataset": _str_or_none(d.get("dataset")), "name": _str_or_none(d.get("name"))}


_CLIMATE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()


@api.post("/climate")
def climate(req: SiteRequest) -> dict[str, Any]:
    """Typical-year hourly series and monthly summaries for the loaded site."""
    if req.site_id in _CLIMATE_CACHE:
        return _CLIMATE_CACHE[req.site_id]
    cached = SITES.get(req.site_id)
    if cached is None:
        raise HTTPException(status_code=409, detail="reload")
    climate_layer = cached[1].get("climate")
    if climate_layer is None or not (climate_layer.data or {}).get("hourly"):
        raise HTTPException(status_code=404, detail="no climate data for this site")
    from sce.climate import climate_summary

    summary = _json_safe(climate_summary(climate_layer))
    _CLIMATE_CACHE[req.site_id] = summary
    while len(_CLIMATE_CACHE) > 8:
        _CLIMATE_CACHE.popitem(last=False)
    return summary


_FILE_NOTES = {
    "dossier.json": "Machine-readable record: AOI, every metric, per-layer provenance, sources.",
    "georef.json": "CRS (WKT), bounds, WGS84 centre and the local origin used by glb/obj.",
    "georef.prj": "The CRS as ESRI WKT, for GIS software that wants a .prj.",
    ".pdf": "A3 site context sheet.",
    ".png": "Raster of the site context sheet.",
    ".dxf": "CAD drawing in projected metres (real-world coordinates).",
    ".3dm": "Rhino model in projected metres (real-world coordinates).",
    ".gpkg": "GeoPackage of all vector layers in projected metres, with metrics.",
    ".geojson": "Vector layers in WGS84 (RFC 7946).",
    ".svg": "Vector drawing in projected metres.",
    ".glb": "3D mesh, metres, local origin (see georef.json), glTF Y-up.",
    ".obj": "3D mesh, metres, local origin (see georef.json), Z-up.",
    ".mtl": "Materials for the .obj.",
    ".epw": "EnergyPlus weather file (typical year from ERA5) for Ladybug, Honeybee, EnergyPlus.",
}


def _readme(aoi: AOI, layers: dict[str, LayerResult], names: list[str]) -> str:
    lon, lat = aoi.centroid_lonlat
    lines = [
        "SITE CONTEXT REPORT EXPORT",
        "==========================",
        "",
        f"Centre (lon, lat): {lon:.6f}, {lat:.6f}",
        f"Square: {2 * (aoi.radius_m or 0):.0f} m x {2 * (aoi.radius_m or 0):.0f} m",
        f"Coordinate system: {aoi.epsg} ({aoi.crs.name}); all units are metres.",
        f"Generated by sce {sce.__version__}.",
        "",
        "Files",
        "-----",
    ]
    for n in names:
        note = _FILE_NOTES.get(n) or _FILE_NOTES.get(Path(n).suffix, "")
        lines.append(f"{n}: {note}".rstrip(": "))
    lines += [
        "",
        "GLB and OBJ meshes are shifted to a local origin (float32 loses precision at",
        "projected-coordinate magnitudes). The origin is in georef.json, under",
        "local_origin: add it back to easting/northing to return to the CRS above.",
        "",
        "Data sources and licences",
        "-------------------------",
    ]
    sources = _dedup_sources(layers)
    for src in sources:
        lines.append(f"- {src['name']} ({src['licence']}) {src['url']}")
    if any("odbl" in s["licence"].lower() or "openstreetmap" in s["name"].lower() for s in sources):
        lines += [
            "",
            "Contains data (c) OpenStreetMap contributors, available under the Open Database",
            "Licence (ODbL) 1.0: https://www.openstreetmap.org/copyright. Exports containing",
            "OSM-derived layers are produced works and must keep this attribution and be",
            "shared under the same licence when redistributed.",
        ]
    return "\n".join(lines) + "\n"


def _iter_file(path: Path) -> Iterator[bytes]:
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            yield chunk


@api.post("/export")
def export(req: ExportRequest) -> StreamingResponse:
    unknown = [f for f in req.formats if f not in pipeline.EXPORTERS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown formats {unknown}; allowed: {sorted(pipeline.EXPORTERS)}",
        )
    formats = list(dict.fromkeys(req.formats))

    layers: dict[str, LayerResult] | None = None
    cached = SITES.get(req.site_id)
    if cached is not None:
        outer, outer_layers = cached
        inner = AOI.from_point(req.lon, req.lat, req.half_width_m, name="site", crs=outer.crs)
        if contains(outer, inner):
            layers = clip_layers(outer_layers, outer, inner)
    if layers is None:
        inner = AOI.from_point(req.lon, req.lat, req.half_width_m, name="site")
        layers = pipeline.fetch_layers(inner, Cache())

    tmp = Path(tempfile.mkdtemp(prefix="sce-export-"))
    try:
        out = tmp / "files"
        written = pipeline.run_report(inner, layers, out, formats, sheet=req.report, georef=True)
        arcnames = [(p, "dossier.json" if p.name.endswith(".dossier.json") else p.name) for p in written]
        # georef writes a sibling .prj that run_report does not list.
        prj = out / "georef.prj"
        if prj.exists() and prj not in written:
            arcnames.append((prj, prj.name))
        names = sorted({a for _, a in arcnames})
        archive = tmp / "bundle.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.txt", _readme(inner, layers, ["README.txt", *names]))
            for path, arc in arcnames:
                zf.write(path, arc)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    fname = f"sce-{req.lat:.5f}-{req.lon:.5f}-{round(req.half_width_m * 2)}m.zip"
    return StreamingResponse(
        _iter_file(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Content-Length": str(archive.stat().st_size),
        },
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


app.include_router(api)
