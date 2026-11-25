"""The Rhino/Grasshopper-native export: a `.3dm` file a designer can open and
immediately reference the massing, alongside `sce/export/dxf.py`.

Real-world metre coordinates in the AOI's projected CRS, model units set to
metres, and layer names matching the DXF exporter one-for-one so the two
exports are interchangeable in a CAD/BIM pipeline: `SITE-BOUNDARY`,
`BLDG-MASSING`, `BLDG-FOOTPRINT`, `ROAD-CENTRELINE`, `TOPO-CONTOUR`.

The honest part: a building only becomes a 3D extrusion on `BLDG-MASSING`
when its height is actually known. Where height is unknown it is written as
a flat curve on `BLDG-FOOTPRINT` instead, so opening the file immediately
shows a designer which buildings are massing model and which are guesses
smoothed over as "not there" would be. Never invent a height.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..types import LayerResult
from ._contours import terrain_contours

_LAYER_NAMES = (
    "SITE-BOUNDARY",
    "BLDG-MASSING",
    "BLDG-FOOTPRINT",
    "ROAD-CENTRELINE",
    "TOPO-CONTOUR",
)

# name -> RGBA, loosely matching the DXF ACI palette so the two exports read
# the same way on screen.
_LAYER_COLOUR: dict[str, tuple[int, int, int, int]] = {
    "SITE-BOUNDARY": (230, 30, 30, 255),
    "BLDG-MASSING": (150, 150, 160, 255),
    "BLDG-FOOTPRINT": (90, 90, 90, 255),
    "ROAD-CENTRELINE": (20, 20, 20, 255),
    "TOPO-CONTOUR": (170, 110, 40, 255),
}


def _require_rhino3dm():
    try:
        import rhino3dm
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "write_3dm() needs the optional 'rhino' extra: install it with "
            "`pip install sce[rhino]` (or `pip install rhino3dm` directly)."
        ) from exc
    return rhino3dm


def _new_document(rhino3dm) -> Any:
    doc = rhino3dm.File3dm()
    doc.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
    doc.Settings.ModelAbsoluteTolerance = 0.001
    for name in _LAYER_NAMES:
        doc.Layers.AddLayer(name, _LAYER_COLOUR[name])
    return doc


def _layer_index(doc, name: str) -> int:
    layer = doc.Layers.FindName(name, None)
    return layer.Index


def _attrs(rhino3dm, doc, layer_name: str):
    attrs = rhino3dm.ObjectAttributes()
    attrs.LayerIndex = _layer_index(doc, layer_name)
    return attrs


def _polygon_parts(geom):
    """(exterior_ring, [hole_rings]) per polygon part, dropping the Z ezdxf-style tuples."""
    parts = []
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for g in geoms:
        if g.is_empty:
            continue
        exterior = [(x, y) for x, y, *_ in g.exterior.coords]
        holes = [[(x, y) for x, y, *_ in interior.coords] for interior in g.interiors]
        parts.append((exterior, holes))
    return parts


def _closed_polyline_curve(rhino3dm, ring: list[tuple[float, float]], z: float = 0.0):
    pts = [rhino3dm.Point3d(x, y, z) for x, y in ring]
    if len(pts) < 4:  # a closed ring needs at least a triangle plus the repeated closing point
        return None
    if pts[0].X != pts[-1].X or pts[0].Y != pts[-1].Y:
        pts.append(pts[0])
    polyline = rhino3dm.Polyline(pts)
    return polyline.ToPolylineCurve()


def _open_polyline_curve(rhino3dm, pts: list[tuple[float, ...]]):
    pts3 = [rhino3dm.Point3d(*p[:3]) if len(p) >= 3 else rhino3dm.Point3d(p[0], p[1], 0.0) for p in pts]
    if len(pts3) < 2:
        return None
    return rhino3dm.Polyline(pts3).ToPolylineCurve()


def _add_boundary(rhino3dm, doc, aoi) -> None:
    curve = _closed_polyline_curve(rhino3dm, list(aoi.geometry.exterior.coords))
    if curve is not None:
        doc.Objects.AddCurve(curve, _attrs(rhino3dm, doc, "SITE-BOUNDARY"))


def _extrusion_for_polygon(
    rhino3dm, exterior: list[tuple[float, float]], holes: list[list[tuple[float, float]]], height: float
):
    outer_curve = _closed_polyline_curve(rhino3dm, exterior)
    if outer_curve is None or not outer_curve.IsClosed:
        return None
    extrusion = rhino3dm.Extrusion.Create(outer_curve, float(height), True)
    if extrusion is None:
        return None
    for hole in holes:
        hole_curve = _closed_polyline_curve(rhino3dm, hole)
        if hole_curve is not None and hole_curve.IsClosed:
            extrusion.AddInnerProfile(hole_curve)
    return extrusion


def _write_buildings(rhino3dm, doc, result: LayerResult | None) -> dict[str, int]:
    counts = {"massing": 0, "footprint_only": 0}
    if result is None or result.gdf is None:
        return counts
    gdf = result.gdf
    heights = gdf["height_m"] if "height_m" in gdf.columns else None
    for i, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        height = None
        if heights is not None:
            h = heights.iloc[i]
            if h is not None and not (isinstance(h, float) and np.isnan(h)) and float(h) > 0:
                height = float(h)
        for exterior, holes in _polygon_parts(geom):
            if height is not None:
                extrusion = _extrusion_for_polygon(rhino3dm, exterior, holes, height)
                if extrusion is not None:
                    doc.Objects.AddExtrusion(extrusion, _attrs(rhino3dm, doc, "BLDG-MASSING"))
                    counts["massing"] += 1
                    continue
            # Height unknown, or extrusion failed on a degenerate ring: the flat
            # footprint still goes on the sheet, honestly labelled as such.
            curve = _closed_polyline_curve(rhino3dm, exterior)
            if curve is not None:
                doc.Objects.AddCurve(curve, _attrs(rhino3dm, doc, "BLDG-FOOTPRINT"))
                counts["footprint_only"] += 1
            for hole in holes:
                hole_curve = _closed_polyline_curve(rhino3dm, hole)
                if hole_curve is not None:
                    doc.Objects.AddCurve(hole_curve, _attrs(rhino3dm, doc, "BLDG-FOOTPRINT"))
    return counts


def _write_streets(rhino3dm, doc, result: LayerResult | None) -> int:
    count = 0
    if result is None or result.gdf is None:
        return count
    for geom in result.gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        geoms = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for g in geoms:
            if g.is_empty or g.geom_type != "LineString":
                continue
            pts = [(x, y, 0.0) for x, y, *_ in g.coords]
            curve = _open_polyline_curve(rhino3dm, pts)
            if curve is not None:
                doc.Objects.AddCurve(curve, _attrs(rhino3dm, doc, "ROAD-CENTRELINE"))
                count += 1
    return count


def _write_contours(rhino3dm, doc, result: LayerResult | None) -> int:
    count = 0
    for elevation, pts in terrain_contours(result):
        curve = _open_polyline_curve(rhino3dm, [(x, y, elevation) for x, y in pts])
        if curve is not None:
            doc.Objects.AddCurve(curve, _attrs(rhino3dm, doc, "TOPO-CONTOUR"))
            count += 1
    return count


def write_3dm(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write buildings (massing where height is known, footprint otherwise),
    streets, terrain contours and the AOI boundary to a metric `.3dm` file."""
    rhino3dm = _require_rhino3dm()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = _new_document(rhino3dm)
    _add_boundary(rhino3dm, doc, aoi)
    _write_buildings(rhino3dm, doc, layers.get("buildings"))
    _write_streets(rhino3dm, doc, layers.get("streets"))
    _write_contours(rhino3dm, doc, layers.get("terrain"))

    doc.Write(str(path), 0)
    return path
