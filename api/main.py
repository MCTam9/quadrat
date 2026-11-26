"""Private site-picker backend: Clerk-authenticated FastAPI over `sce.site.Site`.

HTTP only: auth, request validation, SSE framing, error mapping and zip
streaming. Everything about a site (padded fetch, clipping, analysis, preview,
climate, export files) lives in `sce/site.py`, where it is tested directly.

`/api/load` builds a `Site` (slow, streamed as SSE) and keeps it in a small
in-process LRU; the other routes view squares inside it. The LRU is per
process: a cold serverless instance will not have it, which is why the square
routes answer 409 `{"error": "reload"}` and the frontend re-runs `/api/load`.
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

import sce
from sce.aoi import AOI
from sce.site import OutsideSite, Site, jsonable, padded_half_width, site_key
from sce.types import LayerResult

__all__ = ["app", "padded_half_width", "site_key"]

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


def _authorized_parties() -> list[str]:
    """CLERK_AUTHORIZED_PARTIES, else this deployment's own origins on Vercel (web and API share them)."""
    parties = [p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()]
    if parties:
        return parties
    hosts = (os.environ.get(k) for k in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"))
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
    parties = _authorized_parties()
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


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _site_and_square(req: SquareRequest) -> tuple[Site, AOI]:
    """The loaded site and the requested square, or 409 telling the client to reload."""
    site = SITES.get(req.site_id)
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


app = FastAPI(title="Quadrat API", lifespan=_lifespan, docs_url=None, redoc_url=None)
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

    def work() -> None:
        try:

            def on_layer(name: str, result: LayerResult | None) -> None:
                emit(
                    "layer",
                    jsonable(
                        {
                            "layer": name,
                            "provider": result.provider if result else None,
                            "features": 0 if result is None or result.gdf is None else len(result.gdf),
                            "coverage": result.coverage if result else None,
                            "ok": result is not None,
                        }
                    ),
                )

            site = Site.load(req.lon, req.lat, req.half_width_m, on_layer=on_layer)
            SITES.put(site)
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
    site = SITES.get(req.site_id)
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


@api.post("/export")
def export(req: ExportRequest) -> StreamingResponse:
    """Zip of the chosen formats. Uses the loaded site when the square fits it, else fetches."""
    site = SITES.get(req.site_id)
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
            files = site.export(square, req.formats, tmp / "files", report=req.report)
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


app.include_router(api)
