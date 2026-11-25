"""Web-friendly export: one RFC 7946 GeoJSON FeatureCollection in WGS84.

RFC 7946 mandates EPSG:4326 lon/lat, so everything is reprojected from the AOI
metric CRS (coordinates rounded to 7 dp, about 1 cm). Each feature carries a
`layer` property so a single file can be filtered in any web map. Licence and
provenance travel in a foreign member (`"sce"`), which RFC 7946 permits, so the
ODbL notice cannot be separated from the data.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, mapping
from shapely.geometry.polygon import orient
from shapely.ops import transform as shapely_transform

from ..aoi import WGS84
from ..types import LayerResult
from ._contours import terrain_contours

_DP = 7
_LAYER_ORDER = ("buildings", "streets", "landuse", "amenities", "constraints")
_ODBL_NOTICE = (
    "Contains OpenStreetMap-derived data (c) OpenStreetMap contributors, "
    "licensed under the Open Database Licence (ODbL). Derived products remain share-alike."
)


def _scalar(value: Any) -> Any:
    """JSON scalar or None. NaN/inf and non-scalars (lists, dicts) become None."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, str):
        return value
    return None


def _is_scalar_column(series) -> bool:
    """True unless the column holds lists/dicts/other containers."""
    return all(not isinstance(v, (list, tuple, dict, set, np.ndarray)) for v in series.dropna())


def _round_geom(geom):
    return shapely.transform(geom, lambda c: np.round(c, _DP))


def _to_wgs84(tf: Transformer, geom):
    out = shapely_transform(lambda x, y, z=None: tf.transform(x, y), geom)
    if out.geom_type == "Polygon":
        out = orient(out, 1.0)  # RFC 7946: exterior counter-clockwise
    elif out.geom_type == "MultiPolygon":
        out = shapely.MultiPolygon([orient(p, 1.0) for p in out.geoms])
    return _round_geom(out)


def _feature(geom, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


def _layer_features(tf: Transformer, name: str, result: LayerResult | None) -> list[dict[str, Any]]:
    if result is None or result.gdf is None or len(result.gdf) == 0:
        return []
    gdf = result.gdf
    if name == "buildings":
        cols = [c for c in gdf.columns if c != gdf.geometry.name and c in ("height_m", "height_source")]
    else:
        cols = [c for c in gdf.columns if c != gdf.geometry.name and _is_scalar_column(gdf[c])]
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        props: dict[str, Any] = {k: _scalar(row[k]) for k in cols if k != "layer"}
        if name == "buildings":
            props.setdefault("height_m", None)
            props.setdefault("height_source", None)
        props["layer"] = name
        features.append(_feature(_to_wgs84(tf, geom), props))
    return features


def _sce_member(aoi, layers: dict[str, LayerResult]) -> dict[str, Any]:
    sources: dict[str, str] = {}
    for result in layers.values():
        if result is None:
            continue
        for src in result.sources:
            sources[src.name] = src.licence
    member: dict[str, Any] = {
        "crs_source": aoi.epsg,
        "licence": [f"{name} - {licence}" for name, licence in sorted(sources.items())],
    }
    if any("openstreetmap" in n.lower() or "osm" in n.lower() for n in sources):
        member["odbl_notice"] = _ODBL_NOTICE
    else:
        member["odbl_notice"] = None
    return member


def write_geojson(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write every vector layer, contours and the AOI boundary as one WGS84
    FeatureCollection with a `layer` property on each feature."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tf = Transformer.from_crs(aoi.crs, WGS84, always_xy=True)

    features: list[dict[str, Any]] = []
    for name in _LAYER_ORDER:
        features.extend(_layer_features(tf, name, layers.get(name)))

    features.append(_feature(_to_wgs84(tf, aoi.geometry), {"layer": "site_boundary", "name": aoi.name}))

    for elevation, pts in terrain_contours(layers.get("terrain")):
        if len(pts) < 2:
            continue
        line = _to_wgs84(tf, LineString(pts))
        features.append(_feature(line, {"layer": "contour", "elevation_m": round(float(elevation), 3)}))

    collection = {
        "type": "FeatureCollection",
        "name": aoi.name,
        "features": features,
        "sce": _sce_member(aoi, layers),
    }
    path.write_text(json.dumps(collection, allow_nan=False), encoding="utf-8")
    return path
