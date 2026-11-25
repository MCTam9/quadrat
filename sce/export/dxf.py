"""The headline export: a metric, real-world DXF an architect can open in CAD.

Real-world metre coordinates in the AOI's projected CRS, `doc.units` and
`$INSUNITS` both set to metres, layers named by CAD convention, and an ODbL
notice baked into the drawing text and into ezdxf's custom metadata store
(the closest DXF gets to a `$COMMENTS` header field).
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..types import LayerResult
from ._contours import terrain_contours

# name -> (ACI colour, lineweight in 1/100 mm, as ezdxf expects)
_LAYER_SPEC: dict[str, tuple[int, int]] = {
    "SITE-BOUNDARY": (1, 25),  # red
    "BLDG-FOOTPRINT": (8, 25),  # dark grey
    "ROAD-CENTRELINE": (7, 18),  # white/black
    "LANDUSE": (3, 9),  # green
    "TOPO-CONTOUR": (30, 9),  # orange-brown
    "TEXT-NOTES": (7, 0),
}


def _ensure_layers(doc) -> None:
    for name, (colour, lw) in _LAYER_SPEC.items():
        if name not in doc.layers:
            doc.layers.add(name=name, color=colour, lineweight=lw)


def _exterior_and_holes(geom) -> list[list[tuple[float, float]]]:
    """Return one ring list per polygon (exterior first, then holes) for a
    Polygon or every part of a MultiPolygon."""
    rings: list[list[tuple[float, float]]] = []
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for g in geoms:
        if g.is_empty:
            continue
        rings.append(list(g.exterior.coords))
        rings.extend(list(interior.coords) for interior in g.interiors)
    return rings


def _add_closed_polyline(msp, ring: list[tuple[float, float]], layer: str) -> None:
    pts = [(x, y) for x, y, *_ in ring]
    if len(pts) < 3:
        return
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def _add_line_geometry(msp, geom, layer: str) -> int:
    count = 0
    geoms = list(geom.geoms) if geom.geom_type in ("MultiLineString",) else [geom]
    for g in geoms:
        if g.is_empty or g.geom_type != "LineString":
            continue
        pts = [(x, y) for x, y, *_ in g.coords]
        if len(pts) < 2:
            continue
        msp.add_lwpolyline(pts, close=False, dxfattribs={"layer": layer})
        count += 1
    return count


def _write_buildings(msp, result: LayerResult | None) -> int:
    count = 0
    if result is None or result.gdf is None:
        return count
    for geom in result.gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        for ring in _exterior_and_holes(geom):
            _add_closed_polyline(msp, ring, "BLDG-FOOTPRINT")
            count += 1
    return count


def _write_streets(msp, result: LayerResult | None) -> int:
    count = 0
    if result is None or result.gdf is None:
        return count
    for geom in result.gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type not in ("LineString", "MultiLineString"):
            continue
        count += _add_line_geometry(msp, geom, "ROAD-CENTRELINE")
    return count


def _write_landuse(msp, result: LayerResult | None) -> int:
    count = 0
    if result is None or result.gdf is None:
        return count
    for geom in result.gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        for ring in _exterior_and_holes(geom):
            _add_closed_polyline(msp, ring, "LANDUSE")
            count += 1
    return count


def _write_contours(msp, result: LayerResult | None) -> int:
    count = 0
    for elevation, pts in terrain_contours(result):
        pl = msp.add_lwpolyline(pts, close=False, dxfattribs={"layer": "TOPO-CONTOUR"})
        pl.set_xdata("SCE", [(1000, f"ELEV={elevation:.3f}")])
        count += 1
    return count


def _add_boundary(msp, aoi) -> None:
    pts = list(aoi.geometry.exterior.coords)
    _add_closed_polyline(msp, pts, "SITE-BOUNDARY")


def _notes_text(aoi, layers: dict[str, LayerResult]) -> list[str]:
    lines = [
        f"Site Context Export: {aoi.name}",
        f"Centre (lon,lat): {aoi.centroid_lonlat[0]:.6f}, {aoi.centroid_lonlat[1]:.6f}",
        f"CRS: {aoi.epsg}",
        f"Area: {aoi.area_ha:.2f} ha ({aoi.area_m2:.0f} m2)",
    ]
    sources: dict[str, str] = {}
    for result in layers.values():
        if result is None:
            continue
        for src in result.sources:
            sources[src.name] = src.licence
    if sources:
        lines.append("Sources:")
        for name, licence in sorted(sources.items()):
            lines.append(f"  {name} - {licence}")
    if any("openstreetmap" in n.lower() or "osm" in n.lower() for n in sources):
        lines.append("Contains OpenStreetMap-derived data (c) OpenStreetMap")
        lines.append("contributors, licensed under the Open Database Licence")
        lines.append("(ODbL). Derived products remain share-alike.")
    return lines


def write_dxf(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write buildings, streets, landuse, terrain contours and the AOI boundary
    to a metric DXF, with a text block carrying provenance and licence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    doc.header["$INSUNITS"] = ezdxf.units.M
    doc.header["$MEASUREMENT"] = 1

    notes = _notes_text(aoi, layers)
    metadata = doc.ezdxf_metadata()
    metadata["sce.licence_notice"] = " | ".join(notes)
    metadata["sce.aoi"] = aoi.name
    metadata["sce.crs"] = aoi.epsg

    _ensure_layers(doc)
    msp = doc.modelspace()

    _add_boundary(msp, aoi)
    _write_buildings(msp, layers.get("buildings"))
    _write_streets(msp, layers.get("streets"))
    _write_landuse(msp, layers.get("landuse"))
    _write_contours(msp, layers.get("terrain"))

    minx, miny, _maxx, maxy = aoi.bounds_metric
    text_y = miny - (maxy - miny) * 0.05 - len(notes) * 2.5
    for i, line in enumerate(notes):
        msp.add_text(
            line,
            height=2.0,
            dxfattribs={"layer": "TEXT-NOTES"},
        ).set_placement((minx, text_y - i * 2.5), align=TextEntityAlignment.LEFT)

    doc.saveas(path)
    return path
