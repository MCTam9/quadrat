"""Quadrat API: Clerk-authenticated FastAPI over `sce.site.Site`.

HTTP only: auth, request validation, SSE framing, error mapping and zip
streaming. Everything about a site (padded fetch, clipping, analysis, preview,
climate, export files) lives in `sce/site.py`, where it is tested directly.

`/api/load` builds a `Site` (slow, streamed as SSE) and keeps it in a small
in-process LRU; the other routes view squares inside it. The LRU is per
process, so each loaded site is also snapshotted to a `sce.store` (private Vercel
Blob in production) and a cold instance restores it from there. Only when neither
holds the site do the square routes answer 409 `{"error": "reload"}`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
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
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send

import sce
from sce.aoi import AOI
from sce.pipeline import overpass_budget_s
from sce.site import OutsideSite, Site, jsonable, layer_geojson, padded_half_width, site_key, square_for_load
from sce.store import SnapshotStore, default_store
from sce.types import LayerResult

__all__ = ["app", "exports", "make_app", "padded_half_width", "site_key"]

log = logging.getLogger("sce.api")

MIN_HALF_WIDTH_M = 50.0
MAX_HALF_WIDTH_M = 1000.0
PING_SECONDS = 10.0
CHUNK_BYTES = 64 * 1024

# ---------------------------------------------------------------- auth


def _auth_disabled() -> bool:
    return os.environ.get("SCE_AUTH_DISABLED") == "1"


def _issuer_from_publishable_key(pk: str) -> str | None:
    """Clerk's Frontend API origin, encoded in the publishable key: `pk_<env>_<base64("<host>$")>`."""
    try:
        _, _, encoded = pk.split("_", 2)
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    except (ValueError, UnicodeDecodeError):
        return None
    return f"https://{host}" if host and "." in host and "/" not in host else None


def _clerk_issuer() -> str | None:
    """CLERK_ISSUER, else derived from the publishable key the Clerk integration provisions."""
    explicit = os.environ.get("CLERK_ISSUER")
    if explicit:
        return explicit
    pk = os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY") or os.environ.get("CLERK_PUBLISHABLE_KEY") or ""
    return _issuer_from_publishable_key(pk) if pk else None


def _jwks_url() -> str:
    url = os.environ.get("CLERK_JWKS_URL")
    if url:
        return url
    issuer = _clerk_issuer()
    if not issuer:
        raise KeyError("CLERK_JWKS_URL or NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
    return issuer.rstrip("/") + "/.well-known/jwks.json"


def _authorized_parties(request: Request | None = None) -> list[str]:
    """CLERK_AUTHORIZED_PARTIES, else the origin the request arrived on plus this deployment's Vercel URLs.

    The web app and the API share one origin, so a token minted by the page the user is on carries that
    origin as `azp`, whichever of the project's domains or aliases they opened.
    """
    parties = [p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()]
    if parties:
        return parties
    hosts = [os.environ.get(k) for k in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL")]
    if request is not None:
        hosts.append(request.headers.get("x-forwarded-host") or request.headers.get("host"))
    return [f"https://{h}" for h in hosts if h]


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(_jwks_url(), cache_keys=True)


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
        issuer = _clerk_issuer()
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
    parties = _authorized_parties(request)
    if parties and claims.get("azp") not in parties:
        log.info("auth rejected: azp %r not authorised", claims.get("azp"))
        raise _unauthorised("unauthorised party")


# ---------------------------------------------------------------- site store


class _SiteStore:
    """Thread-safe LRU of loaded sites, keyed by `Site.key`."""

    def __init__(self, capacity: int = 8) -> None:
        self.capacity = capacity
        self._items: OrderedDict[str, Site] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, site: Site) -> None:
        with self._lock:
            self._items[site.key] = site
            self._items.move_to_end(site.key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def get(self, key: str | None) -> Site | None:
        if key is None:
            return None
        with self._lock:
            site = self._items.get(key)
            if site is not None:
                self._items.move_to_end(key)
            return site

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


SITES = _SiteStore(8)

# Shared snapshot store; None disables snapshots. Tests replace it.
STORE: SnapshotStore | None = default_store()


def _restore(key: str | None) -> Site | None:
    """A site from the snapshot store, or None. Never raises: snapshots are an optimisation."""
    if key is None or STORE is None:
        return None
    try:
        data = STORE.get(key)
        return Site.restore(data) if data else None
    except Exception:
        log.warning("snapshot restore failed for %s", key, exc_info=True)
        return None


SNAPSHOT_WAIT_S = 15.0


def _save_snapshot(site: Site) -> None:
    """Write `site` to the store, waiting at most SNAPSHOT_WAIT_S. Never raises.

    Synchronous on purpose: once the response ends Vercel may freeze the instance and lose a
    background upload. Callers run this on the load worker thread, so SSE pings keep flowing.
    """
    store = STORE
    if store is None:
        return

    def run() -> None:
        try:
            store.put(site.key, site.snapshot())
        except Exception:
            log.warning("snapshot write failed for %s", site.key, exc_info=True)

    thread = threading.Thread(target=run, name="sce-snapshot", daemon=True)
    thread.start()
    thread.join(SNAPSHOT_WAIT_S)
    if thread.is_alive():
        log.warning("snapshot write for %s still running after %.0f s; continuing", site.key, SNAPSHOT_WAIT_S)


def _lookup(key: str | None) -> Site | None:
    """The site for `key`: in memory, else restored from the store (and kept in memory)."""
    site = SITES.get(key)
    if site is None:
        site = _restore(key)
        if site is not None and site.key == key:
            SITES.put(site)
        else:
            site = None
    return site


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
    # The place name the web panel shows, for the PDF sheet's header.
    title: str | None = Field(default=None, max_length=120)


# ---------------------------------------------------------------- helpers


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _site_and_square(req: SquareRequest) -> tuple[Site, AOI]:
    """The loaded site and the requested square, or 409 telling the client to reload."""
    site = _lookup(req.site_id)
    if site is None:
        raise HTTPException(status_code=409, detail="reload")
    try:
        return site, site.square(req.lon, req.lat, req.half_width_m)
    except OutsideSite as exc:
        raise HTTPException(status_code=409, detail="reload") from exc


# ---------------------------------------------------------------- app

CORS_ORIGINS = [o.strip() for o in os.environ.get("SCE_CORS_ORIGINS", "").split(",") if o.strip()]


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    if _auth_disabled():
        log.warning("SCE_AUTH_DISABLED=1: authentication is OFF. Local development only.")
    yield


class _SelectiveGZip(GZipMiddleware):
    """GZip for the JSON routes only.

    The `/api/load` event stream must reach the browser event by event, and the
    export zip is already compressed. Newer Starlette skips both by content
    type; this does not depend on the installed version doing so.
    """

    UNCOMPRESSED_PATHS = frozenset({"/api/load", "/api/export"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") in self.UNCOMPRESSED_PATHS:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    return JSONResponse({"error": f"invalid {loc}: {first.get('msg', 'bad request')}"}, status_code=422)


async def _internal_error(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse({"error": "internal error"}, status_code=500)


def health() -> dict[str, Any]:
    return {"ok": True, "version": sce.__version__}


def make_app(title: str) -> FastAPI:
    """A FastAPI app with the shared middleware, error shapes and `/api/health`, but no routes.

    Both deployed functions build their app here: this module's `app` (site routes plus export,
    which is what local development runs) and `api/export.py` (export only).
    """
    app = FastAPI(title=title, lifespan=_lifespan, docs_url=None, redoc_url=None)
    # Added first so CORS (added next) wraps it: CORS headers land on compressed responses too.
    app.add_middleware(_SelectiveGZip, minimum_size=1024)
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["Content-Disposition"],
        )
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _internal_error)
    app.add_api_route("/api/health", health, methods=["GET"])
    return app


api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
# Export has its own router so `api/export.py` can serve it alone: it is the only route that
# needs the report and CAD stack (matplotlib, ezdxf, rhino3dm, trimesh), which the site
# function's bundle leaves out.
exports = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@api.post("/load")
async def load(req: LoadRequest) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def emit(event: str, data: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    outer = AOI.from_point(req.lon, req.lat, padded_half_width(req.half_width_m), name="padded")
    square = None if req.half_width_m is None else square_for_load(req.lon, req.lat, req.half_width_m, outer)

    def on_layer(name: str, result: LayerResult | None, ms: int) -> None:
        with draft_lock:
            settled.add(name)
        event = {
            "layer": name,
            "provider": result.provider if result else None,
            "features": 0 if result is None or result.gdf is None else len(result.gdf),
            "coverage": result.coverage if result else None,
            "ok": result is not None,
            "ms": ms,
        }
        if square is not None:
            try:
                event["geojson"] = layer_geojson(name, result, outer, square)
            except Exception:
                # Drawing early is a bonus; the final preview still arrives.
                log.warning("early geojson for %s failed", name, exc_info=True)
        if event.get("geojson") is None:
            event.pop("geojson", None)
        emit("layer", jsonable(event))

    # Layers that have been reported, as a draft or for real: a draft is emitted at most once
    # and never after the real layer.
    settled: set[str] = set()
    draft_lock = threading.Lock()

    def on_draft(name: str, result: LayerResult, ms: int) -> None:
        """A quick map-tile version of a layer, flagged `draft`; the real layer's event replaces it."""
        with draft_lock:
            # `fetch_layers` already refuses a draft after its layer; this is the second lock.
            if name in settled:
                return
            settled.add(name)
        event = {
            "layer": name,
            "draft": True,
            "provider": result.provider,
            "features": 0 if result.gdf is None else len(result.gdf),
            "coverage": result.coverage,
            "ok": True,
            "ms": ms,
        }
        if square is not None:
            try:
                event["geojson"] = layer_geojson(name, result, outer, square)
            except Exception:
                log.warning("draft geojson for %s failed", name, exc_info=True)
        if event.get("geojson") is None:
            event.pop("geojson", None)
        emit("layer", jsonable(event))

    def emit_final_buildings(site: Site) -> None:
        """Buildings again once LiDAR heights and building use are in, same shape as a layer event."""
        if square is None or "buildings" not in site.layers:
            return
        try:
            parts = site.preview_parts(site.square(req.lon, req.lat, req.half_width_m), ["buildings"])
        except Exception:
            log.warning("final buildings geojson failed", exc_info=True)
            return
        emit("layer", {"layer": "buildings", "update": True, "geojson": parts["buildings"]})

    def work() -> None:
        try:
            key = site_key(req.lon, req.lat, padded_half_width(req.half_width_m))
            known = _lookup(key)
            if known is not None:
                for name, result in known.layers.items():
                    on_layer(name, result, 0)
                emit_final_buildings(known)
                emit("ready", known.ready())
                return
            site = Site.load(
                req.lon,
                req.lat,
                req.half_width_m,
                on_layer=on_layer,
                on_draft=on_draft,
                overpass_budget_s=overpass_budget_s(),
            )
            SITES.put(site)
            emit_final_buildings(site)
            _save_snapshot(site)  # before `ready`: see _save_snapshot
            emit("ready", site.ready())
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
    site, square = _site_and_square(req)
    return site.analyse(square)


@api.post("/preview")
def preview(req: SquareRequest) -> dict[str, Any]:
    site, square = _site_and_square(req)
    return site.preview(square)


@api.post("/climate")
def climate(req: SiteRequest) -> dict[str, Any]:
    """Typical-year hourly series and monthly summaries for the loaded site."""
    site = _lookup(req.site_id)
    if site is None:
        raise HTTPException(status_code=409, detail="reload")
    summary = site.climate()
    if summary is None:
        raise HTTPException(status_code=404, detail="no climate data for this site")
    return summary


def _iter_file(path: Path) -> Iterator[bytes]:
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            yield chunk


@exports.post("/export")
def export(req: ExportRequest) -> StreamingResponse:
    """Zip of the chosen formats. Uses the loaded site when the square fits it, else fetches."""
    site = _lookup(req.site_id)
    square = None
    if site is not None:
        try:
            square = site.square(req.lon, req.lat, req.half_width_m)
        except OutsideSite:
            site = None
    if site is None or square is None:
        site = Site.for_square(req.lon, req.lat, req.half_width_m)
        square = site.square(req.lon, req.lat, req.half_width_m)

    tmp = Path(tempfile.mkdtemp(prefix="sce-export-"))
    try:
        try:
            files = site.export(square, req.formats, tmp / "files", report=req.report, title=req.title)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        archive = tmp / "bundle.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                zf.write(path, path.name)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    fname = f"quadrat-{req.lat:.5f}-{req.lon:.5f}-{round(req.half_width_m * 2)}m.zip"
    return StreamingResponse(
        _iter_file(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Content-Length": str(archive.stat().st_size),
        },
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


# Local development and tests run everything in one app. On Vercel `/api/export` is routed to
# `api/export.py` instead (vercel.json), so this copy of the route is never reached there.
app = make_app("Quadrat API")
app.include_router(api)
app.include_router(exports)
