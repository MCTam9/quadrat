"""Georeferencing sidecar written next to every export bundle.

DXF, 3DM, SVG and GPKG carry real-world projected metres, but nothing in a
DXF says *which* projection. Meshes (GLB/OBJ) are shifted to a local origin
because float32 vertices lose centimetres at UTM magnitudes. This sidecar
records both, so any file in the bundle can be put back where it belongs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def local_origin(aoi: Any) -> tuple[float, float]:
    """The metric-CRS point mesh exports subtract from every vertex."""
    c = aoi.geometry.centroid
    return (round(float(c.x), 3), round(float(c.y), 3))


def georef_dict(aoi: Any) -> dict[str, Any]:
    """Everything a GIS or CAD user needs to re-place the bundle on the earth."""
    ox, oy = local_origin(aoi)
    lon, lat = aoi.centroid_lonlat
    return {
        "crs": aoi.epsg,
        "crs_wkt": aoi.crs.to_wkt(),
        "units": "metre",
        "centre_lonlat": [round(lon, 7), round(lat, 7)],
        "bbox_wgs84": [round(v, 7) for v in aoi.bbox_wgs84],
        "bounds_metric": [round(v, 3) for v in aoi.bounds_metric],
        "real_world_coordinates": ["dxf", "3dm", "svg", "gpkg"],
        "local_origin": {
            "applies_to": ["glb", "obj"],
            "easting": ox,
            "northing": oy,
            "note": "Mesh vertices are (easting - origin, northing - origin, elevation). "
            "glTF is Y-up (x=east, y=up, z=-north); OBJ is Z-up (x=east, y=north, z=up).",
        },
        "geojson_crs": "EPSG:4326 (RFC 7946)",
    }


def write_georef(path: str | Path, aoi: Any) -> Path:
    """Write `georef.json` plus a `.prj` with the CRS as ESRI-readable WKT."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(georef_dict(aoi), indent=2))
    path.with_suffix(".prj").write_text(aoi.crs.to_wkt(version="WKT1_ESRI"))
    return path
