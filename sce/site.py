"""A site: layers fetched once for a padded square, viewed through any smaller one.

The web app's whole lifecycle lives here, so HTTP is left with validation,
streaming and error mapping. A `Site` owns:

- the padded fetch (`Site.load`), sized to the square the user starts with;
- one clip per square (`layers_for`), shared by analysis, preview and export,
  with building use attached so every view agrees;
- the views: `analyse`, `preview`, `climate`, `export`.

Fetching is injected (`fetch=`), so tests build a `Site` from fixture layers
with no network, through the same interface the API uses.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from . import pipeline
from .aoi import AOI
from .clip import clip_layers, contains
from .types import LayerResult

# The padded fetch is sized to the square the user starts with, plus room to
# drag. A fixed 3 km x 3 km fetch was too heavy for the public Overpass servers.
PADDED_MAX_HALF_WIDTH_M = 1500.0
PADDED_MIN_HALF_WIDTH_M = 750.0
PADDED_MARGIN_M = 500.0
# Buildings drawn around the square for 3D context.
CONTEXT_RING_M = 250.0
MAX_FEATURES = 20000

Fetch = Callable[..., dict[str, LayerResult]]


class OutsideSite(ValueError):
    """The requested square is not inside the fetched area; load the site again."""


class NoData(RuntimeError):
    """No provider returned anything for this location."""


def padded_half_width(half_width_m: float | None) -> float:
    """Half-width of the padded fetch for a square of this half-width (None -> the maximum)."""
    if half_width_m is None:
        return PADDED_MAX_HALF_WIDTH_M
    return min(PADDED_MAX_HALF_WIDTH_M, max(PADDED_MIN_HALF_WIDTH_M, half_width_m + PADDED_MARGIN_M))


def site_key(lon: float, lat: float, padded_half_width_m: float = PADDED_MAX_HALF_WIDTH_M) -> str:
    """Stable identity for a loaded site."""
    return f"{lon:.5f},{lat:.5f},{padded_half_width_m:.0f}"


class Site:
    """Layers for one fetched area, and every view of any square inside it."""

    def __init__(self, outer: AOI, layers: dict[str, LayerResult]) -> None:
        self.outer = outer
        self.layers = layers
        self._views: OrderedDict[tuple[float, float, float], dict[str, LayerResult]] = OrderedDict()
        self._lock = threading.Lock()
        self._climate: dict[str, Any] | None = None

    # -- construction --------------------------------------------------------

    @classmethod
    def load(
        cls,
        lon: float,
        lat: float,
        half_width_m: float | None = None,
        *,
        cache: Any = None,
        fetch: Fetch | None = None,
        on_layer: Callable[[str, LayerResult | None], None] | None = None,
    ) -> Site:
        """Fetch a padded square around (lon, lat) once. Slow: this is the network step."""
        outer = AOI.from_point(lon, lat, padded_half_width(half_width_m), name="padded")
        return cls._fetch(outer, cache, fetch, on_layer)

    @classmethod
    def for_square(
        cls, lon: float, lat: float, half_width_m: float, *, cache: Any = None, fetch: Fetch | None = None
    ) -> Site:
        """A site exactly the size of one square, for one-off exports with no loaded site."""
        return cls._fetch(AOI.from_point(lon, lat, half_width_m, name="site"), cache, fetch, None)

    @classmethod
    def _fetch(cls, outer: AOI, cache: Any, fetch: Fetch | None, on_layer: Any) -> Site:
        from .cache import Cache

        # Looked up at call time so tests can substitute sce.pipeline.fetch_layers.
        fetch = fetch or pipeline.fetch_layers
        layers = fetch(outer, cache or Cache(), on_layer=on_layer)
        if not layers:
            raise NoData("no data available for this location")
        return cls(outer, layers)

    @property
    def key(self) -> str:
        lon, lat = self.outer.centroid_lonlat
        return site_key(lon, lat, self.outer.radius_m or 0.0)

    def ready(self) -> dict[str, Any]:
        """What a client needs once the site has loaded."""
        lon, lat = self.outer.centroid_lonlat
        return {
            "site_id": self.key,
            "epsg": self.outer.epsg,
            "centre": [lon, lat],
            "padded_half_width_m": self.outer.radius_m,
            "bbox_wgs84": [round(v, 6) for v in self.outer.bbox_wgs84],
        }

    # -- squares -------------------------------------------------------------

    def square(self, lon: float, lat: float, half_width_m: float) -> AOI:
        """The inner square, in this site's CRS. Raises OutsideSite if it does not fit."""
        inner = AOI.from_point(lon, lat, half_width_m, name="site", crs=self.outer.crs)
        if not contains(self.outer, inner):
            raise OutsideSite(f"square at {lon:.5f},{lat:.5f} r={half_width_m:.0f} is outside {self.key}")
        return inner

    def layers_for(self, square: AOI) -> dict[str, LayerResult]:
        """Layers clipped to `square`, with building use attached. One clip per square."""
        lon, lat = square.centroid_lonlat
        key = (round(lon, 7), round(lat, 7), float(square.radius_m or 0.0))
        with self._lock:
            if key in self._views:
                self._views.move_to_end(key)
                return self._views[key]
        layers = clip_layers(self.layers, self.outer, square)
        layers = _with_building_use(layers)
        with self._lock:
            self._views[key] = layers
            while len(self._views) > 16:
                self._views.popitem(last=False)
        return layers

    # -- views ---------------------------------------------------------------

    def analyse(self, square: AOI) -> dict[str, Any]:
        """Metrics, coverage assessment and per-layer provenance for `square` (JSON-safe)."""
        layers = self.layers_for(square)
        metrics, assessment = pipeline.analyse(layers, square)
        return jsonable(
            {
                "aoi": {**square.provenance(), "square": _geometry(square.geometry_wgs84)},
                "metrics": metrics,
                "assessment": assessment,
                "layers": {
                    name: {
                        "provider": r.provider,
                        "coverage": r.coverage,
                        "degraded": bool(r.degraded),
                        "notes": r.provenance()["notes"],
                    }
                    for name, r in sorted(layers.items())
                },
            }
        )

    def preview(self, square: AOI) -> dict[str, Any]:
        """WGS84 GeoJSON for drawing `square` on a web map (JSON-safe)."""
        layers = self.layers_for(square)
        gdf = _gdf(layers.get("buildings"))
        contours, interval = _contours(layers.get("terrain"), square)
        return jsonable(
            {
                "square": {"type": "Feature", "geometry": _geometry(square.geometry_wgs84), "properties": {}},
                "buildings": _collection(gdf, _building_props),
                "streets": _collection(_gdf(layers.get("streets")), _street_props),
                "landuse": _collection(_gdf(layers.get("landuse")), _landuse_props),
                "contours": _collection(contours, lambda r: {"elevation_m": r.get("elevation_m")}),
                "contour_interval_m": interval,
                "constraints": _collection(_gdf(layers.get("constraints")), _constraint_props),
                "context": _collection(
                    self._context(square), lambda r: {"height_m": _num(r.get("height_m"))}
                ),
            }
        )

    def climate(self) -> dict[str, Any] | None:
        """Typical-year and monthly climate for the site, or None without climate data."""
        if self._climate is None:
            layer = self.layers.get("climate")
            if layer is None or not (layer.data or {}).get("hourly"):
                return None
            from .climate import climate_summary

            self._climate = jsonable(climate_summary(layer))
        return self._climate

    def export(self, square: AOI, formats: list[str], out: Path, *, report: bool = True) -> list[Path]:
        """Write the chosen formats, the dossier, georef sidecars and a README into `out`.

        Returns every file written, README first. Raises ValueError for an unknown format.
        """
        from .export.bundle import write_readme

        unknown = [f for f in formats if f not in pipeline.EXPORTERS]
        if unknown:
            raise ValueError(f"unknown formats {unknown}; allowed: {sorted(pipeline.EXPORTERS)}")
        layers = self.layers_for(square)
        written = pipeline.run_report(
            square, layers, out, list(dict.fromkeys(formats)), sheet=report, georef=True
        )
        files: list[Path] = []
        for p in written:
            if p.name.endswith(".dossier.json"):
                p = p.rename(p.with_name("dossier.json"))
            files.append(p)
        prj = out / "georef.prj"
        if prj.exists() and prj not in files:
            files.append(prj)
        readme = write_readme(
            out / "README.txt", square, layers, ["README.txt", *sorted(f.name for f in files)]
        )
        return [readme, *files]

    def _context(self, square: AOI) -> Any:
        """Buildings in a ring around the square, for context massing."""
        b = _gdf(self.layers.get("buildings"))
        if b is None or not len(b):
            return None
        ring = square.geometry.buffer(CONTEXT_RING_M, join_style="mitre").difference(square.geometry)
        ring = ring.intersection(self.outer.geometry)
        clipped = b[b.intersects(ring)].clip(ring)
        keep = [c for c in ("height_m",) if c in clipped.columns]
        return clipped[[*keep, clipped.geometry.name]]


# -- helpers (private) ---------------------------------------------------------


def _with_building_use(layers: dict[str, LayerResult]) -> dict[str, LayerResult]:
    from dataclasses import replace

    from .building_use import infer_building_use

    b = layers.get("buildings")
    if b is None or b.gdf is None or not len(b.gdf):
        return layers
    am, lu = layers.get("amenities"), layers.get("landuse")
    uses = infer_building_use(b.gdf, am.gdf if am is not None else None, lu.gdf if lu is not None else None)
    gdf = b.gdf.assign(use=uses["use"], use_source=uses["use_source"])
    return {**layers, "buildings": replace(b, gdf=gdf)}


def _gdf(result: LayerResult | None) -> Any:
    return None if result is None else result.gdf


def _contours(terrain: LayerResult | None, square: AOI) -> tuple[Any, float | None]:
    if terrain is None or terrain.raster is None:
        return None, None
    import geopandas as gpd
    from shapely.geometry import LineString

    from .export._contours import choose_contour_interval, terrain_contours

    arr = np.asarray(terrain.raster["array"], dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None, None
    lines = terrain_contours(terrain)
    gdf = gpd.GeoDataFrame(
        {"elevation_m": [round(z, 1) for z, _ in lines]},
        geometry=[LineString(pts) for _, pts in lines],
        crs=square.crs,
    )
    return square.clip(gdf), choose_contour_interval(float(finite.min()), float(finite.max()))


def _geometry(geom: Any) -> dict[str, Any]:
    import shapely
    from shapely.geometry import mapping

    return dict(mapping(shapely.transform(geom, lambda c: np.round(c, 6))))


def _collection(gdf: Any, props: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    if gdf is not None and len(gdf):
        gdf = gdf.to_crs(4326)
        # Plain dicts, not itertuples: namedtuples rename `class` and `building:levels`.
        rows = gdf.drop(columns=gdf.geometry.name).to_dict("records")
        for geom, row in zip(gdf.geometry, rows, strict=True):
            if geom is None or geom.is_empty:
                continue
            features.append({"type": "Feature", "geometry": _geometry(geom), "properties": props(row)})
            if len(features) >= MAX_FEATURES:
                break
    return {"type": "FeatureCollection", "features": features}


def _text(v: Any) -> str | None:
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return str(v)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _building_props(row: dict[str, Any]) -> dict[str, Any]:
    src = row.get("height_source")
    return {
        "height_m": _num(row.get("height_m")),
        "height_source": src if isinstance(src, str) else "",
        "building": _text(row.get("building")),
        "levels": _num(row.get("building:levels")),
        "use": _text(row.get("use")),
        "use_source": _text(row.get("use_source")),
    }


def _context_props(row: dict[str, Any]) -> dict[str, Any]:
    return {"height_m": _num(row.get("height_m"))}


def _street_props(row: dict[str, Any]) -> dict[str, Any]:
    return {"highway": _text(row.get("highway")) or ""}


def _landuse_props(row: dict[str, Any]) -> dict[str, Any]:
    from .vocab import normalise_landuse

    return {"class": normalise_landuse(_text(row.get("class")))}


def _constraint_props(row: dict[str, Any]) -> dict[str, Any]:
    return {"dataset": _text(row.get("dataset")), "name": _text(row.get("name"))}


_DROP = object()


def _safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, np.generic):
        return _safe(obj.item())
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            s = _safe(v)
            if s is not _DROP:
                out[str(k)] = s
        return out
    if isinstance(obj, (list, tuple, set)):
        return [s for s in (_safe(v) for v in obj) if s is not _DROP]
    return _DROP


def jsonable(obj: Any) -> Any:
    """Reduce to JSON types: NaN/inf -> None, numpy scalars -> Python, graphs/arrays dropped."""
    out = _safe(obj)
    return None if out is _DROP else out
