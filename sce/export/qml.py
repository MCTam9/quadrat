"""Hand-written minimal QML styles so the GeoPackage opens styled, not grey.

QML is QGIS's documented style XML. We emit the smallest form QGIS 3.x will
accept: a `<qgis>` root wrapping a `<renderer-v2>`. ArcGIS Pro reads the same
`.qml` sidecar convention for a `.gpkg` layer.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

from ..types import LayerResult
from ..vocab import LANDUSE, colours


def _rgba(hex_colour: str) -> str:
    h = hex_colour.lstrip("#")
    return ",".join(str(int(h[i : i + 2], 16)) for i in (0, 2, 4)) + ",255"


# From sce/vocab.py: the same classes the provider emits.
_LANDUSE_COLOURS: dict[str, str] = {k: _rgba(v) for k, v in colours(LANDUSE, sheet=True).items()}

_SINGLE_SYMBOL_STYLE = {
    "buildings": {"type": "fill", "color": "60,60,60,255", "outline": "0,0,0,0", "width": "0"},
    "streets": {"type": "line", "color": "40,40,40,255", "width": "0.4"},
}


def _fill_symbol_xml(
    colour: str, outline_colour: str = "0,0,0,255", outline_width: str = "0.2"
) -> ET.Element:
    symbol = ET.Element("symbol", {"type": "fill", "name": "0", "alpha": "1"})
    layer = ET.SubElement(symbol, "layer", {"class": "SimpleFill", "enabled": "1"})
    for key, val in {
        "color": colour,
        "outline_color": outline_colour,
        "outline_width": outline_width,
        "outline_style": "solid",
        "style": "solid",
    }.items():
        ET.SubElement(layer, "Option", {"type": "QString", "name": key, "value": val})
    return symbol


def _line_symbol_xml(colour: str, width: str, dash: bool = False) -> ET.Element:
    symbol = ET.Element("symbol", {"type": "line", "name": "0", "alpha": "1"})
    layer = ET.SubElement(symbol, "layer", {"class": "SimpleLine", "enabled": "1"})
    opts = {
        "line_color": colour,
        "line_width": width,
        "line_style": "solid",
        "capstyle": "square",
    }
    if dash:
        opts["use_custom_dash"] = "1"
        opts["customdash"] = "4;2"
        opts["line_style"] = "dash"
    for key, val in opts.items():
        ET.SubElement(layer, "Option", {"type": "QString", "name": key, "value": val})
    return symbol


def _single_symbol_renderer(symbol: ET.Element) -> ET.Element:
    renderer = ET.Element("renderer-v2", {"type": "singleSymbol"})
    symbols = ET.SubElement(renderer, "symbols")
    symbols.append(symbol)
    return renderer


def _categorized_renderer(field: str, classes: dict[str, str]) -> ET.Element:
    renderer = ET.Element(
        "renderer-v2",
        {"type": "categorizedSymbol", "attr": field, "symbollevels": "0"},
    )
    symbols = ET.SubElement(renderer, "symbols")
    categories = ET.SubElement(renderer, "categories")
    for i, (value, colour) in enumerate(classes.items()):
        symbol = _fill_symbol_xml(colour)
        symbol.set("name", str(i))
        symbols.append(symbol)
        ET.SubElement(
            categories,
            "category",
            {"value": escape(str(value)), "symbol": str(i), "label": escape(str(value)), "render": "true"},
        )
    return renderer


def _qgis_doc(renderer: ET.Element) -> ET.Element:
    root = ET.Element("qgis", {"version": "3.34", "styleCategories": "AllStyleCategories"})
    root.append(renderer)
    return root


def _write(root: ET.Element, out_path: Path) -> Path:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    ET.parse(out_path)  # verify it parses back
    return out_path


def _style_for_layer(name: str, result: LayerResult | None) -> ET.Element:
    if name == "buildings":
        return _qgis_doc(_single_symbol_renderer(_fill_symbol_xml("60,60,60,255", "0,0,0,0", "0")))
    if name == "streets":
        return _qgis_doc(_single_symbol_renderer(_line_symbol_xml("40,40,40,255", "0.4")))
    if name == "aoi":
        return _qgis_doc(_single_symbol_renderer(_fill_symbol_xml("0,0,0,0", "230,20,20,255", "0.6")))
    if name in ("landuse", "landcover"):
        classes = dict(_LANDUSE_COLOURS)
        col = None
        if result is not None and result.gdf is not None:
            for candidate in ("class", "landuse", "landcover", "category"):
                if candidate in result.gdf.columns:
                    col = candidate
                    break
        col = col or "class"
        return _qgis_doc(_categorized_renderer(col, classes))
    return _qgis_doc(_single_symbol_renderer(_fill_symbol_xml("180,180,180,255")))


def write_qml_styles(gpkg_path: str | Path, layers: dict[str, LayerResult]) -> list[Path]:
    """Emit one `<layer>.qml` beside the GeoPackage for every spatial layer.

    QGIS auto-loads a same-named `.qml` sidecar (`<layer>.qml` next to the
    `.gpkg`, matching the GPKG layer name) when a project references the layer
    by its default style; ArcGIS Pro also honours the sidecar convention.
    """
    gpkg_path = Path(gpkg_path)
    out_dir = gpkg_path.parent
    written: list[Path] = []

    names = ["aoi", *sorted(k for k in layers if k != "aoi")]
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        result = layers.get(name)
        if name != "aoi" and (result is None or result.gdf is None or len(result.gdf) == 0):
            continue
        doc = _style_for_layer(name, result)
        out_path = out_dir / f"{gpkg_path.stem}_{name}.qml"
        written.append(_write(doc, out_path))
    return written
