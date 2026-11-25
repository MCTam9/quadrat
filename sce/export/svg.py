"""Plan drawing as SVG, for Illustrator, Inkscape and the browser.

1 user unit = 1 metre, origin at the AOI top-left (x = X - minx, y = maxy - Y),
so the drawing is to scale at any export size. Layer groups carry
`inkscape:groupmode="layer"` and the same names as the DXF, which both Inkscape
and Illustrator import as real layers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..types import LayerResult
from ..vocab import LANDUSE, colours, normalise_landuse
from ._contours import terrain_contours
from .dxf import _notes_text

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
ET.register_namespace("", SVG_NS)
ET.register_namespace("inkscape", INKSCAPE_NS)

LAYER_NAMES = (
    "SITE-BOUNDARY",
    "BLDG-FOOTPRINT",
    "ROAD-CENTRELINE",
    "LANDUSE",
    "TOPO-CONTOUR",
    "TEXT-NOTES",
)

_Z_ORDER = ("LANDUSE", "TOPO-CONTOUR", "ROAD-CENTRELINE", "BLDG-FOOTPRINT", "SITE-BOUNDARY", "TEXT-NOTES")

# Stroke width in metres of drawing, by OSM highway class.
_STREET_WIDTH = {
    "motorway": 8.0,
    "trunk": 7.0,
    "primary": 6.0,
    "secondary": 5.0,
    "tertiary": 4.0,
    "residential": 3.0,
    "unclassified": 3.0,
    "service": 2.0,
    "living_street": 2.5,
}
_STREET_DEFAULT = 1.5  # footways, tracks, paths and unknown classes

# From sce/vocab.py: keyed on the classes the provider actually emits.
_LANDUSE_FILL = colours(LANDUSE, sheet=True)
_LANDUSE_DEFAULT = "#ececec"


def _q(name: str) -> str:
    return f"{{{INKSCAPE_NS}}}{name}"


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _path_d(rings, tx, ty, close: bool) -> str:
    parts = []
    for ring in rings:
        pts = [(tx(x), ty(y)) for x, y, *_ in ring]
        if len(pts) < 2:
            continue
        seg = "M" + " L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts)
        parts.append(seg + (" Z" if close else ""))
    return " ".join(parts)


def _pts_d(pts, close: bool) -> str:
    return "M" + " L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts) + (" Z" if close else "")


def _polygon_rings(geom) -> list:
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    rings = []
    for g in geoms:
        if g.is_empty or g.geom_type != "Polygon":
            continue
        rings.append(list(g.exterior.coords))
        rings.extend(list(i.coords) for i in g.interiors)
    return rings


def _lines(geom) -> list:
    geoms = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
    return [list(g.coords) for g in geoms if g.geom_type == "LineString" and not g.is_empty]


def _layer_group(root, name: str) -> ET.Element:
    return ET.SubElement(root, "g", {"id": name, _q("groupmode"): "layer", _q("label"): name})


def _text(parent, x: float, y: float, s: str, size: float, anchor: str = "start") -> None:
    el = ET.SubElement(
        parent,
        "text",
        {
            "x": _fmt(x),
            "y": _fmt(y),
            "font-size": _fmt(size),
            "font-family": "Helvetica, Arial, sans-serif",
            "fill": "#222",
            "text-anchor": anchor,
        },
    )
    el.text = s


def write_svg(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write a to-scale plan SVG (1 unit = 1 m) with one group per CAD layer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    minx, miny, maxx, maxy = aoi.bounds_metric
    w, h = maxx - minx, maxy - miny

    def tx(x: float) -> float:
        return x - minx

    def ty(y: float) -> float:
        return maxy - y

    notes = _notes_text(aoi, layers)
    text_size = max(w / 90.0, 1.0)
    line_h = text_size * 1.35
    margin = max(w * 0.04, 5.0)
    strip = margin + len(notes) * line_h + margin  # title strip below the plan
    vb = (-margin, -margin, w + 2 * margin, h + margin + strip)

    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "viewBox": " ".join(_fmt(v) for v in vb),
            "width": _fmt(vb[2]),
            "height": _fmt(vb[3]),
        },
    )
    ET.SubElement(root, "title").text = f"Quadrat export: {aoi.name}"
    ET.SubElement(
        root,
        "rect",
        {"x": _fmt(vb[0]), "y": _fmt(vb[1]), "width": _fmt(vb[2]), "height": _fmt(vb[3]), "fill": "#fff"},
    )

    # Element order is z-order: fills at the bottom, notes on top.
    groups = {name: _layer_group(root, name) for name in _Z_ORDER}

    # Site boundary
    ET.SubElement(
        groups["SITE-BOUNDARY"],
        "path",
        {
            "d": _path_d([list(aoi.geometry.exterior.coords)], tx, ty, True),
            "fill": "none",
            "stroke": "#d00",
            "stroke-width": "0.5",
        },
    )

    # Landuse
    lu = layers.get("landuse")
    if lu is not None and lu.gdf is not None:
        cls_col = next((c for c in ("class", "landuse", "kind") if c in lu.gdf.columns), None)
        for _, row in lu.gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            fill = (
                _LANDUSE_FILL.get(normalise_landuse(row[cls_col]), _LANDUSE_DEFAULT)
                if cls_col
                else _LANDUSE_DEFAULT
            )
            ET.SubElement(
                groups["LANDUSE"],
                "path",
                {
                    "d": _path_d(_polygon_rings(geom), tx, ty, True),
                    "fill": fill,
                    "fill-rule": "evenodd",
                    "stroke": "none",
                },
            )

    # Contours
    for elevation, pts in terrain_contours(layers.get("terrain")):
        p = ET.SubElement(
            groups["TOPO-CONTOUR"],
            "path",
            {"d": _path_d([pts], tx, ty, False), "fill": "none", "stroke": "#a0693c", "stroke-width": "0.15"},
        )
        ET.SubElement(p, "title").text = f"{elevation:g} m"

    # Streets
    st = layers.get("streets")
    if st is not None and st.gdf is not None:
        for _, row in st.gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            hw = str(row["highway"]).lower() if "highway" in st.gdf.columns else ""
            width = _STREET_WIDTH.get(hw, _STREET_DEFAULT)
            d = _path_d(_lines(geom), tx, ty, False)
            if d:
                ET.SubElement(
                    groups["ROAD-CENTRELINE"],
                    "path",
                    {
                        "d": d,
                        "fill": "none",
                        "stroke": "#555",
                        "stroke-width": _fmt(width),
                        "stroke-linecap": "round",
                        "stroke-linejoin": "round",
                    },
                )

    # Buildings
    bl = layers.get("buildings")
    if bl is not None and bl.gdf is not None:
        for geom in bl.gdf.geometry:
            if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            ET.SubElement(
                groups["BLDG-FOOTPRINT"],
                "path",
                {
                    "d": _path_d(_polygon_rings(geom), tx, ty, True),
                    "fill": "#444",
                    "fill-rule": "evenodd",
                    "stroke": "#111",
                    "stroke-width": "0.2",
                },
            )

    # Notes: scale bar, north arrow, title block text
    g = groups["TEXT-NOTES"]
    bar = 100.0 if w >= 400 else 50.0 if w >= 150 else 10.0
    bx, by = w * 0.02, h - h * 0.03
    scale_pts = [(bx, by - 2), (bx, by), (bx + bar, by), (bx + bar, by - 2)]
    ET.SubElement(
        g,
        "path",
        {"d": _pts_d(scale_pts, False), "fill": "none", "stroke": "#000", "stroke-width": "0.5"},
    )
    _text(g, bx + bar / 2, by - 3, f"{_fmt(bar)} m", text_size, "middle")
    nx, ny = w - w * 0.04, h * 0.12
    arrow = [(nx, ny - h * 0.07), (nx - h * 0.02, ny), (nx, ny - h * 0.015), (nx + h * 0.02, ny)]
    ET.SubElement(g, "path", {"d": _pts_d(arrow, True), "fill": "#000"})
    _text(g, nx, ny - h * 0.07 - 2, "N", text_size * 1.5, "middle")
    y0 = h + margin + line_h
    for i, line in enumerate(notes):
        _text(g, 0, y0 + i * line_h, line, text_size)

    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path
