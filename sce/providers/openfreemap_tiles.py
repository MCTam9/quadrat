"""Quick, approximate layers from OpenFreeMap vector tiles (OpenMapTiles schema).

Overpass is the detailed source and takes minutes; a z14 tile takes a fraction of a
second. This module fetches the tiles covering an AOI once, decodes them once, and
serves four registered providers from that one decode:

- `tiles_buildings`, `tiles_streets`, `tiles_landuse`, `tiles_amenities`.

They are ranked after the OSM providers, so they are a fallback in the registry
chain, and the loader (`sce.pipeline.fetch_layers`) also draws them as "drafts"
while Overpass is still running and stands them in when Overpass misses its budget.
Every tile-derived result is `degraded` with a note saying so.

What the tiles lose, and how each layer copes:

- buildings: no OSM id, type or levels. Buildings with equal attributes are merged
  into MultiPolygons, so they are exploded to parts; parts split along a tile seam
  are dissolved back together. `height_m` is `render_height` when above zero.
- streets: lines are not noded at junctions, so there is no graph and the graph
  metrics report "not available". Classes are mapped to OSM `highway` values.
- landuse: landuse, landcover, park and water polygons mapped through
  `sce.vocab.OMT_LANDUSE`.
- amenities: `poi` points mapped to the amenity categories; street furniture
  (bollards, gates, bins) is dropped.

Tile geometry is in 4096-unit tile pixels with y down. It is converted to exact
tile-grid coordinates first (integer tile index plus pixel/4096, exact in a float),
so two neighbouring tiles agree bit for bit on their shared edge, then to Web
Mercator and the AOI's metric CRS.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import shape

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ..vocab import omt_landuse_class
from ._buildings import summarise_building_heights
from .osm_landuse import summarise_landuse

log = logging.getLogger("sce.providers.tiles")

TILEJSON_URL = "https://tiles.openfreemap.org/planet"
USER_AGENT = "quadrat (site analysis)"
ZOOM = 14
EXTENT = 4096
TIMEOUT_S = 15
MAX_WORKERS = 8
TILEJSON_TTL_S = 3600.0
MEMO_MAX = 4
MEMO_TTL_S = 600.0
# Half the circumference of Web Mercator.
_MERC = 20037508.342789244

TILE_LAYERS = ("buildings", "streets", "landuse", "amenities")
CREDIT = "OpenMapTiles © OpenMapTiles, © OpenStreetMap contributors (ODbL), via OpenFreeMap"

NOTES = {
    "buildings": "From map tiles: building counts and types approximate",
    "streets": (
        "From map tiles: street classes simplified and there is no street graph, "
        "so intersection, reach and orientation metrics are not available"
    ),
    "landuse": "From map tiles: land-use classes approximate",
    "amenities": "From map tiles: amenities approximate (points of interest only)",
}


# -- network ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT}


def _get_tilejson() -> dict[str, Any]:
    r = requests.get(TILEJSON_URL, headers=_headers(), timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def _get_tile(url: str) -> bytes:
    """Tile bytes; a 404 is an empty tile (open sea, nothing mapped)."""
    r = requests.get(url, headers=_headers(), timeout=TIMEOUT_S)
    if r.status_code == 404:
        return b""
    r.raise_for_status()
    return r.content


_tilejson_lock = threading.Lock()
_tilejson: tuple[float, str, str] | None = None  # (fetched at, url template, version)


def tile_template() -> tuple[str, str]:
    """(url template with {z}/{x}/{y}, version) from the TileJSON, cached in process for an hour.

    The URL carries the planet build's version, which changes weekly; it is never hardcoded.
    """
    global _tilejson
    with _tilejson_lock:
        if _tilejson is not None and time.monotonic() - _tilejson[0] < TILEJSON_TTL_S:
            return _tilejson[1], _tilejson[2]
        template = _get_tilejson()["tiles"][0]
        m = re.search(r"/planet/([^/]+)/\{z\}", template)
        version = m.group(1) if m else "unversioned"
        _tilejson = (time.monotonic(), template, version)
        return template, version


# -- tile arithmetic -------------------------------------------------------------------


def lonlat_to_tile(lon: float, lat: float, z: int = ZOOM) -> tuple[int, int]:
    n = 2**z
    lat = max(min(lat, 85.0511287798), -85.0511287798)
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_for_bbox(w: float, s: float, e: float, n: float, z: int = ZOOM) -> list[tuple[int, int]]:
    x0, y1 = lonlat_to_tile(w, s, z)
    x1, y0 = lonlat_to_tile(e, n, z)
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def tile_bounds_lonlat(x: int, y: int, z: int = ZOOM) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a tile in degrees."""
    n = 2**z

    def lat(ty: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))

    return x / n * 360.0 - 180.0, lat(y + 1), (x + 1) / n * 360.0 - 180.0, lat(y)


def grid_to_mercator(coords: np.ndarray, z: int = ZOOM) -> np.ndarray:
    """Tile-grid coordinates (tile index + fraction, y down) to Web Mercator metres."""
    size = 2 * _MERC / 2**z
    out = np.empty_like(coords, dtype=float)
    out[:, 0] = -_MERC + coords[:, 0] * size
    out[:, 1] = _MERC - coords[:, 1] * size
    return out


# -- decoding --------------------------------------------------------------------------

_ROAD_CLASS = {
    "motorway": "motorway",
    "trunk": "trunk",
    "primary": "primary",
    "secondary": "secondary",
    "tertiary": "tertiary",
    "minor": "residential",
    "service": "service",
    "track": "track",
}
_PATH_SUBCLASS = {
    "footway": "footway",
    "pedestrian": "pedestrian",
    "path": "path",
    "cycleway": "cycleway",
    "steps": "steps",
    "bridleway": "bridleway",
    "corridor": "footway",
    "platform": "footway",
}


def road_highway(cls: object, subclass: object = None) -> str | None:
    """OSM `highway` value for an OpenMapTiles transportation class; None for rail, ferries, etc."""
    c = str(cls)
    if c in _ROAD_CLASS:
        return _ROAD_CLASS[c]
    if c == "path":
        return _PATH_SUBCLASS.get(str(subclass), "path")
    return None


_FOOD = {"restaurant", "fast_food", "cafe", "bar", "beer", "pub", "ice_cream", "food_court", "biergarten"}
_RETAIL_CLASSES = {
    "shop",
    "grocery",
    "butcher",
    "bakery",
    "supermarket",
    "convenience",
    "marketplace",
    "florist",
    "alcohol_shop",
    "furniture",
    "mall",
    "department_store",
}
_EDUCATION = {"school", "college", "university", "kindergarten", "library"}
_HEALTH = {"hospital", "doctors", "pharmacy", "dentist", "veterinary", "clinic"}
_TRANSPORT = {
    "bus",
    "railway",
    "harbor",
    "ferry_terminal",
    "parking",
    "bicycle_parking",
    "bicycle_rental",
    "charging_station",
    "fuel",
    "taxi",
    "airport",
    "aerialway",
}
_CIVIC = {
    "town_hall",
    "courthouse",
    "police",
    "fire_station",
    "place_of_worship",
    "embassy",
    "social_facility",
    "community_centre",
    "prison",
}
_LEISURE = {
    "cinema",
    "theatre",
    "nightclub",
    "fitness_centre",
    "sports_centre",
    "swimming",
    "playground",
    "golf",
    "stadium",
    "museum",
    "art_gallery",
    "attraction",
    "zoo",
}


def poi_category(cls: object, subclass: object = None) -> str | None:
    """Amenity category (as `osm_amenities` assigns) for a tile POI; None for street furniture.

    Bollards, gates, bins, gardens and the like are dropped: `osm_amenities` would not
    list them as amenities, and thousands of them would swamp the real ones.
    """
    c = str(cls)
    if c in _FOOD:
        return "food"
    if c in _RETAIL_CLASSES or c.endswith("_store") or c.endswith("_shop"):
        return "retail"
    if c in _EDUCATION:
        return "education"
    if c in _HEALTH:
        return "health"
    if c in _TRANSPORT:
        return "transport"
    if c == "post":
        return "civic" if str(subclass) == "post_office" else None
    if c in _CIVIC:
        return "civic"
    if c in _LEISURE:
        return "leisure"
    return None


def _clean(v: Any) -> Any:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


# Source layer -> (property columns kept, geometry kind). Everything else is dropped on decode.
_WANTED: dict[str, tuple[list[str], str]] = {
    "building": (["render_height", "render_min_height", "colour", "hide_3d"], "Polygon"),
    # Transportation also holds pedestrian areas and bridge polygons: lines only.
    "transportation": (["class", "subclass", "brunnel"], "LineString"),
    "poi": (["class", "subclass", "name"], "Point"),
    "landuse": (["class"], "Polygon"),
    "landcover": (["class", "subclass"], "Polygon"),
    "park": (["class"], "Polygon"),
    "water": (["class"], "Polygon"),
}
_TYPE_ID = {"Point": 0, "LineString": 1, "Polygon": 3}


def _empty(columns: list[str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        pd.DataFrame(columns=["edge", *columns]), geometry=gpd.GeoSeries([], dtype="geometry")
    )


def _layer_frame(feats: list[dict[str, Any]], layer: str, tx: int, ty: int) -> gpd.GeoDataFrame:
    """One source layer of one tile as a frame in tile-grid coordinates, cut to the tile.

    Done array-at-a-time: a z14 city tile holds thousands of parts, and per-geometry
    Python calls were the slow part of the load.
    """
    columns, kind = _WANTED[layer]
    if not feats:
        return _empty(columns)
    geoms = np.array([shape(f["geometry"]) for f in feats], dtype=object)
    parts, src = shapely.get_parts(geoms, return_index=True)
    keep = shapely.get_type_id(parts) == _TYPE_ID[kind]
    parts, src = parts[keep], src[keep]
    if kind == "Point":
        # Points in the tile's pixel buffer belong to the neighbouring tile.
        x, y = shapely.get_x(parts), shapely.get_y(parts)
        inside = (x >= 0) & (x < EXTENT) & (y >= 0) & (y < EXTENT)
        parts, src = parts[inside], src[inside]
    if len(parts) == 0:
        return _empty(columns)
    grid = shapely.transform(parts, lambda c: c / EXTENT + np.array([tx, ty], dtype=float))
    edge = np.zeros(len(grid), dtype=bool)
    if kind != "Point":
        # Tiles carry a pixel buffer that their neighbours also carry: cut to the tile's own square.
        minx, miny, maxx, maxy = shapely.bounds(grid).T
        spill = (minx < tx) | (miny < ty) | (maxx > tx + 1) | (maxy > ty + 1)
        if spill.any():
            sub = grid[spill]
            bad = ~shapely.is_valid(sub)
            if bad.any():
                sub[bad] = shapely.make_valid(sub[bad])
            cut_parts, cut_src = shapely.get_parts(
                shapely.clip_by_rect(sub, tx, ty, tx + 1, ty + 1), return_index=True
            )
            ok = (shapely.get_type_id(cut_parts) == _TYPE_ID[kind]) & ~shapely.is_empty(cut_parts)
            spill_src = src[spill][cut_src[ok]]
            grid = np.concatenate([grid[~spill], cut_parts[ok]])
            src = np.concatenate([src[~spill], spill_src])
        if len(grid) == 0:
            return _empty(columns)
        minx, miny, maxx, maxy = shapely.bounds(grid).T
        edge = (minx <= tx) | (miny <= ty) | (maxx >= tx + 1) | (maxy >= ty + 1)
    props = [f["properties"] for f in feats]
    df = pd.DataFrame({c: [_clean(props[i].get(c)) for i in src] for c in columns}, columns=columns)
    df.insert(0, "edge", edge)
    return gpd.GeoDataFrame(df, geometry=grid)


def _decode_tile(data: bytes, tx: int, ty: int) -> dict[str, gpd.GeoDataFrame]:
    """Every wanted source layer of one tile, as frames in tile-grid coordinates."""
    if not data:
        return {layer: _empty(cols) for layer, (cols, _) in _WANTED.items()}
    import mapbox_vector_tile

    tile = mapbox_vector_tile.decode(data, default_options={"y_coord_down": True})
    return {layer: _layer_frame(tile.get(layer, {}).get("features", []), layer, tx, ty) for layer in _WANTED}


# -- fetching one load's tiles ---------------------------------------------------------


def _tile_frames(cache: Any, template: str, version: str, tx: int, ty: int) -> dict[str, gpd.GeoDataFrame]:
    url = template.format(z=ZOOM, x=tx, y=ty)

    def produce() -> tuple[bytes, dict[str, Any]]:
        return _get_tile(url), {"url": url, "licence": "ODbL 1.0 / OpenMapTiles", "version": version}

    data, _ = cache.get_bytes(cache.key("ofm", version, ZOOM, tx, ty), ".pbf", produce)
    return _decode_tile(data, tx, ty)


def _dissolve_seams(gdf: gpd.GeoDataFrame, keys: list[str], *, lines: bool = False) -> gpd.GeoDataFrame:
    """Union features that touch a tile edge and share attributes, then explode to single parts.

    A feature cut by a tile seam arrives as two pieces with equal attributes meeting on
    the seam; unioning them restores one feature. Pieces that do not touch an edge cannot
    be split and are left alone, so equal-attribute buildings elsewhere stay separate.
    """
    kind = "LineString" if lines else "Polygon"
    if gdf.empty:
        return gdf.drop(columns=["edge"])
    if not lines:
        # Tile rings are not always valid (a hole drawn outside its shell); union needs valid input.
        geoms = gdf.geometry.to_numpy().copy()
        bad = ~shapely.is_valid(geoms)
        if bad.any():
            geoms[bad] = shapely.make_valid(geoms[bad])
            gdf = gdf.set_geometry(gpd.GeoSeries(geoms, index=gdf.index))
    on_edge = gdf["edge"].astype(bool)  # object dtype after concatenating empty frames
    edge, rest = gdf[on_edge], gdf[~on_edge]
    if len(edge) > 1:
        merged = edge.dissolve(by=keys, dropna=False, as_index=False)[[*keys, "geometry"]]
        if lines:
            merged["geometry"] = merged.geometry.apply(shapely.line_merge)
        gdf = pd.concat([rest[[*keys, "geometry"]], merged], ignore_index=True)
    else:
        gdf = gdf[[*keys, "geometry"]]
    exploded = gpd.GeoDataFrame(gdf, geometry="geometry").explode(index_parts=False)
    return exploded[exploded.geom_type == kind].reset_index(drop=True)


def _to_aoi_crs(gdf: gpd.GeoDataFrame, aoi: Any) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.set_crs(aoi.crs, allow_override=True)
    gdf = gdf.copy()
    gdf["geometry"] = shapely.transform(gdf.geometry.to_numpy(), grid_to_mercator)
    return gdf.set_crs(3857, allow_override=True).to_crs(aoi.crs)


def _source() -> Source:
    return Source(
        name="OpenMapTiles © OpenMapTiles, © OpenStreetMap contributors (via OpenFreeMap vector tiles)",
        url="https://openfreemap.org/",
        licence="ODbL 1.0",
        licence_url="https://www.openstreetmap.org/copyright",
        note=(
            "Approximate layers decoded from OpenFreeMap z14 vector tiles (OpenMapTiles schema, "
            "CC-BY 4.0; data ODbL 1.0)"
        ),
        commercial_ok=True,
    )


def _build_layers(frames: dict[str, gpd.GeoDataFrame], aoi: Any) -> dict[str, gpd.GeoDataFrame]:
    out: dict[str, gpd.GeoDataFrame] = {}

    # buildings: ground-level parts only; parts with a min_height are raised roofs over another part.
    keys = ["render_height", "render_min_height", "colour", "hide_3d"]
    b = frames["building"]
    b = b[~(pd.to_numeric(b["render_min_height"], errors="coerce").fillna(0) > 0)]
    b = _dissolve_seams(b, keys)
    if len(b):
        height = pd.to_numeric(b["render_height"], errors="coerce")
        b["height_m"] = height.where(height > 0, np.nan).astype(float)
        b["height_source"] = np.where(b["height_m"].notna(), "tiles", "")
    out["buildings"] = b

    # streets
    roads = frames["transportation"].copy()
    roads["highway"] = [road_highway(c, s) for c, s in zip(roads["class"], roads["subclass"], strict=True)]
    roads = roads[roads["highway"].notna()]
    roads["omt_class"] = roads["class"]
    keys = ["highway", "omt_class", "subclass", "brunnel"]
    out["streets"] = _dissolve_seams(roads, keys, lines=True)

    # landuse: landuse, landcover, park, water, drawn in that order (water on top)
    parts = []
    for layer in ("landuse", "landcover", "park", "water"):
        f = frames[layer].copy()
        if "subclass" not in f.columns:
            f["subclass"] = None
        f["omt_layer"] = layer
        f["omt_class"] = f["class"]
        f["class"] = [omt_landuse_class(layer, c) for c in f["omt_class"]]
        parts.append(
            f[f["class"].notna()][["edge", "class", "omt_layer", "omt_class", "subclass", "geometry"]]
        )
    keys = ["class", "omt_layer", "omt_class", "subclass"]
    out["landuse"] = _dissolve_seams(gpd.GeoDataFrame(pd.concat(parts, ignore_index=True)), keys)

    # amenities
    p = frames["poi"].copy()
    p["category"] = [poi_category(c, s) for c, s in zip(p["class"], p["subclass"], strict=True)]
    p = p[p["category"].notna()]
    p["omt_class"] = p["class"]
    out["amenities"] = p[["category", "omt_class", "subclass", "name", "geometry"]].reset_index(drop=True)

    return {k: _to_aoi_crs(v, aoi) for k, v in out.items()}


def _clip_and_summarise(
    layer: str, gdf: gpd.GeoDataFrame, aoi: Any, extra_notes: list[str]
) -> LayerResult | None:
    gdf = aoi.clip(gdf)
    if gdf is None or len(gdf) == 0:
        return None
    gdf = gdf[~gdf.geometry.is_empty].reset_index(drop=True)
    if len(gdf) == 0:
        return None
    result = LayerResult(
        layer=layer,
        provider=f"tiles_{layer}",
        gdf=gdf,
        sources=[_source()],
        notes=[NOTES[layer], *extra_notes],
    )
    return _PROVIDERS[layer].summarise(result, aoi)


_memo: OrderedDict[str, tuple[float, dict[str, LayerResult]]] = OrderedDict()
_memo_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def tile_results(aoi: Any, cache: Any) -> dict[str, LayerResult]:
    """The four tile layers for `aoi`, from one fetch and decode shared by every caller.

    Concurrent callers for the same AOI (the draft thread and a registry fallback) wait for
    the one in flight and get the same answer. Layers with nothing in them are absent.
    Raises when the tiles cannot be fetched at all; failures are not memoised.
    """
    key = f"{cache.root}|{aoi.key()}"
    with _memo_lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        with _memo_lock:
            hit = _memo.get(key)
            if hit is not None and time.monotonic() - hit[0] < MEMO_TTL_S:
                _memo.move_to_end(key)
                return hit[1]
        results = _fetch_and_build(aoi, cache)
        with _memo_lock:
            _memo[key] = (time.monotonic(), results)
            while len(_memo) > MEMO_MAX:
                _memo.popitem(last=False)
        return results


def _fetch_and_build(aoi: Any, cache: Any) -> dict[str, LayerResult]:
    if cache.offline:
        raise FileNotFoundError("offline: map tiles are not fetched")
    started = time.perf_counter()
    template, version = tile_template()
    tiles = tiles_for_bbox(*aoi.bbox_wgs84)
    failed: list[str] = []

    def one(t: tuple[int, int]) -> dict[str, gpd.GeoDataFrame] | None:
        try:
            return _tile_frames(cache, template, version, *t)
        except Exception as exc:
            log.warning("tile %s failed: %s", t, exc)
            failed.append(f"{t[0]}/{t[1]}")
            return None

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tiles))) as pool:
        decoded = list(pool.map(one, tiles))
    if len(failed) == len(tiles):
        raise RuntimeError(f"could not fetch any of {len(tiles)} map tiles")
    frames = {
        layer: gpd.GeoDataFrame(
            pd.concat([d[layer] for d in decoded if d is not None], ignore_index=True), geometry="geometry"
        )
        for layer in _WANTED
    }

    extra = (
        [f"{len(failed)} of {len(tiles)} map tiles were unavailable, so the edges may be bare"]
        if failed
        else []
    )
    results: dict[str, LayerResult] = {}
    for layer, gdf in _build_layers(frames, aoi).items():
        res = _clip_and_summarise(layer, gdf, aoi, extra)
        if res is not None:
            results[layer] = res
    log.info(
        "tiles %d fetched+decoded in %.0f ms: %s",
        len(tiles),
        (time.perf_counter() - started) * 1000,
        {k: len(v.gdf) for k, v in results.items()},
    )
    return results


# -- providers -------------------------------------------------------------------------


class _TilesProvider(Provider):
    """Serves one layer from the shared tile decode. Always degraded."""

    licence = "ODbL 1.0"
    rank = 90  # after every OSM and Overture provider
    commercial_ok = True
    credit = CREDIT

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        got = tile_results(aoi, cache).get(self.layer)
        if got is None:
            raise RuntimeError(f"{self.name}: no {self.layer} features in the map tiles for this AOI")
        # The memoised result is shared; callers (the registry) append to notes.
        return replace(
            got,
            gdf=got.gdf.copy(),
            notes=list(got.notes),
            findings=list(got.findings),
            sources=list(got.sources),
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        out = self._summarise(result, aoi)
        notes = list(out.notes)
        if NOTES[self.layer] not in notes:
            notes.insert(0, NOTES[self.layer])
        return replace(out, degraded=True, notes=notes)

    def _summarise(self, result: LayerResult, aoi) -> LayerResult:
        return result


class TilesBuildingsProvider(_TilesProvider):
    name = "tiles_buildings"
    layer = "buildings"

    def _summarise(self, result: LayerResult, aoi) -> LayerResult:
        return summarise_building_heights(result)


class TilesStreetsProvider(_TilesProvider):
    name = "tiles_streets"
    layer = "streets"


class TilesLanduseProvider(_TilesProvider):
    name = "tiles_landuse"
    layer = "landuse"

    def _summarise(self, result: LayerResult, aoi) -> LayerResult:
        return summarise_landuse(result, aoi)


class TilesAmenitiesProvider(_TilesProvider):
    name = "tiles_amenities"
    layer = "amenities"

    def _summarise(self, result: LayerResult, aoi) -> LayerResult:
        n = result.gdf["category"].nunique() if result.gdf is not None and len(result.gdf) else 0
        return replace(result, coverage=min(n / 8.0, 1.0))


_PROVIDERS: dict[str, _TilesProvider] = {
    p.layer: p
    for p in (
        TilesBuildingsProvider(),
        TilesStreetsProvider(),
        TilesLanduseProvider(),
        TilesAmenitiesProvider(),
    )
}
for _p in _PROVIDERS.values():
    REGISTRY.register(_p)
