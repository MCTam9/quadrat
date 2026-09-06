"""The headline export: a metric, real-world DXF an architect can open in CAD.

Real-world metre coordinates in the AOI's projected CRS, `doc.units` and
`$INSUNITS` both set to metres, layers named by CAD convention, and an ODbL
notice baked into the drawing text and into ezdxf's custom metadata store
(the closest DXF gets to a `$COMMENTS` header field).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ezdxf
import numpy as np
from ezdxf.enums import TextEntityAlignment

from ..types import LayerResult

# name -> (ACI colour, lineweight in 1/100 mm, as ezdxf expects)
_LAYER_SPEC: dict[str, tuple[int, int]] = {
    "SITE-BOUNDARY": (1, 25),  # red
    "BLDG-FOOTPRINT": (8, 25),  # dark grey
    "ROAD-CENTRELINE": (7, 18),  # white/black
    "LANDUSE": (3, 9),  # green
    "TOPO-CONTOUR": (30, 9),  # orange-brown
    "TEXT-NOTES": (7, 0),
}

_CONTOUR_INTERVALS = (1.0, 2.0, 5.0, 10.0, 25.0)


def _ensure_layers(doc) -> None:  # noqa: ANN001
    for name, (colour, lw) in _LAYER_SPEC.items():
        if name not in doc.layers:
            doc.layers.add(name=name, color=colour, lineweight=lw)


def _exterior_and_holes(geom) -> list[list[tuple[float, float]]]:  # noqa: ANN001
    """Return one ring list per polygon (exterior first, then holes) for a
    Polygon or every part of a MultiPolygon."""
    rings: list[list[tuple[float, float]]] = []
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for g in geoms:
        if g.is_empty:
            continue
        rings.append(list(g.exterior.coords))
        for interior in g.interiors:
            rings.append(list(interior.coords))
    return rings


def _add_closed_polyline(msp, ring: list[tuple[float, float]], layer: str) -> None:  # noqa: ANN001
    pts = [(x, y) for x, y, *_ in ring]
    if len(pts) < 3:
        return
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})


def _add_line_geometry(msp, geom, layer: str) -> int:  # noqa: ANN001
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


def _write_buildings(msp, result: LayerResult | None) -> int:  # noqa: ANN001
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


def _write_streets(msp, result: LayerResult | None) -> int:  # noqa: ANN001
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


def _write_landuse(msp, result: LayerResult | None) -> int:  # noqa: ANN001
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


def _choose_contour_interval(zmin: float, zmax: float) -> float:
    span = max(zmax - zmin, 1e-6)
    target = span / 8.0
    for interval in _CONTOUR_INTERVALS:
        if interval >= target:
            return interval
    return _CONTOUR_INTERVALS[-1]


def _contour_segments(array: np.ndarray, transform, interval: float) -> list[tuple[float, list[tuple[float, float]]]]:
    """(elevation, [(x, y), ...]) pairs in metric coordinates.

    `matplotlib.contour.ContourSet.allsegs` returns, per requested level, a
    list of (N, 2) arrays already in whatever coordinate system X/Y were
    given in — so building X/Y from the affine transform up front means the
    contour vertices come out already in metric CRS coordinates, no separate
    reprojection step needed. `allsegs` is deprecated in newer matplotlib but
    still present in 3.11.x (verified against the installed version); if a
    future upgrade removes it, `get_paths()` is the vectorized fallback.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows, cols = array.shape
    row_idx, col_idx = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    xs, ys = transform @ (col_idx + 0.5, row_idx + 0.5)

    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return []
    zmin, zmax = float(finite.min()), float(finite.max())
    if zmax - zmin < 1e-9:
        return []
    levels = list(np.arange(np.floor(zmin / interval) * interval, zmax + interval, interval))
    levels = [lv for lv in levels if zmin < lv < zmax]
    if not levels:
        return []

    fig, ax = plt.subplots()
    try:
        cs = ax.contour(xs, ys, array, levels=levels)
        out: list[tuple[float, list[tuple[float, float]]]] = []
        if hasattr(cs, "allsegs"):
            for level, segs in zip(cs.levels, cs.allsegs):
                for seg in segs:
                    if len(seg) >= 2:
                        out.append((float(level), [(float(x), float(y)) for x, y in seg]))
        else:  # pragma: no cover - fallback for matplotlib >= 3.10 collections removal
            for level, path in zip(cs.levels, cs.get_paths()):
                for polygon in path.to_polygons():
                    if len(polygon) >= 2:
                        out.append((float(level), [(float(x), float(y)) for x, y in polygon]))
        return out
    finally:
        plt.close(fig)


def _write_contours(msp, result: LayerResult | None) -> int:  # noqa: ANN001
    if result is None or result.raster is None:
        return 0
    raster = result.raster
    array = raster.get("array")
    transform = raster.get("transform")
    if array is None or transform is None:
        return 0
    array = np.asarray(array, dtype=float)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return 0
    interval = _choose_contour_interval(float(finite.min()), float(finite.max()))
    count = 0
    for elevation, pts in _contour_segments(array, transform, interval):
        pl = msp.add_lwpolyline(pts, close=False, dxfattribs={"layer": "TOPO-CONTOUR"})
        pl.set_xdata("SCE", [(1000, f"ELEV={elevation:.3f}")])
        count += 1
    return count


def _add_boundary(msp, aoi) -> None:  # noqa: ANN001
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


def write_dxf(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:  # noqa: ANN001
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

    minx, miny, maxx, maxy = aoi.bounds_metric
    text_y = miny - (maxy - miny) * 0.05 - len(notes) * 2.5
    for i, line in enumerate(notes):
        msp.add_text(
            line,
            height=2.0,
            dxfattribs={"layer": "TEXT-NOTES"},
        ).set_placement((minx, text_y - i * 2.5), align=TextEntityAlignment.LEFT)

    doc.saveas(path)
    return path
