"""SVG export tests against synthetic fixtures. Zero network."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, Polygon, box

from sce.aoi import AOI
from sce.export.svg import INKSCAPE_NS, LAYER_NAMES, SVG_NS, write_svg
from sce.raster import SiteRaster
from sce.types import LayerResult, Source


@pytest.fixture
def aoi() -> AOI:
    return AOI.from_point(lon=-0.1, lat=51.5, radius_m=500.0, name="test-site")


def _building_square(cx: float, cy: float, half: float) -> Polygon:
    return box(cx - half, cy - half, cx + half, cy + half)


@pytest.fixture
def buildings_gdf(aoi: AOI) -> gpd.GeoDataFrame:
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    geoms = [
        _building_square(cx - 100, cy - 100, 10),  # 20x20 = 400 m2
        _building_square(cx + 100, cy + 100, 15),  # 30x30 = 900 m2
    ]
    return gpd.GeoDataFrame(
        {"height_m": [10.0, 20.0], "levels": [3, 6], "tags": [{"a": 1}, {"b": 2}]},
        geometry=geoms,
        crs=aoi.crs,
    )


@pytest.fixture
def streets_gdf(aoi: AOI) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = aoi.bounds_metric
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    horiz = LineString([(minx, cy), (maxx, cy)])
    vert = LineString([(cx, miny), (cx, maxy)])
    return gpd.GeoDataFrame({"highway": ["primary", "secondary"]}, geometry=[horiz, vert], crs=aoi.crs)


@pytest.fixture
def landuse_gdf(aoi: AOI) -> gpd.GeoDataFrame:
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    return gpd.GeoDataFrame(
        {"class": ["residential", "park"]},
        geometry=[
            box(cx - 400, cy - 400, cx, cy),
            box(cx, cy, cx + 400, cy + 400),
        ],
        crs=aoi.crs,
    )


@pytest.fixture
def terrain_raster(aoi: AOI) -> SiteRaster:
    minx, miny, maxx, maxy = aoi.bounds_metric
    res = 10.0
    cols = int((maxx - minx) / res)
    rows = int((maxy - miny) / res)
    transform = Affine(res, 0, minx, 0, -res, maxy)
    row_idx, col_idx = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    xs, ys = transform * (col_idx + 0.5, row_idx + 0.5)
    # A tilted plane: elevation rises 1m per 100m eastward. Known slope, known contours.
    array = (xs - minx) / 100.0
    return SiteRaster.from_array(array, transform, aoi.crs, square=aoi)


@pytest.fixture
def layers(aoi, buildings_gdf, streets_gdf, landuse_gdf, terrain_raster) -> dict[str, LayerResult]:
    src = Source(name="synthetic-osm", url="https://example.invalid", licence="ODbL")
    return {
        "buildings": LayerResult(
            layer="buildings", provider="synthetic", gdf=buildings_gdf, sources=[src], coverage=1.0
        ),
        "streets": LayerResult(
            layer="streets", provider="synthetic", gdf=streets_gdf, sources=[src], coverage=1.0
        ),
        "landuse": LayerResult(
            layer="landuse", provider="synthetic", gdf=landuse_gdf, sources=[src], coverage=0.8
        ),
        "terrain": LayerResult(
            layer="terrain",
            provider="synthetic",
            raster=terrain_raster,
            sources=[Source(name="synthetic-dem", url="https://example.invalid", licence="CC-BY-4.0")],
            coverage=1.0,
        ),
    }


def _parse(tmp_path, aoi, layers):
    out = write_svg(tmp_path / "site.svg", layers, aoi)
    return ET.parse(out).getroot()


def test_svg_has_inkscape_layer_groups(tmp_path, aoi, layers):
    root = _parse(tmp_path, aoi, layers)
    groups = {g.get("id"): g for g in root.findall(f"{{{SVG_NS}}}g")}
    assert set(groups) == set(LAYER_NAMES)
    for name, g in groups.items():
        assert g.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
        assert g.get(f"{{{INKSCAPE_NS}}}label") == name


def test_svg_building_count_and_content(tmp_path, aoi, layers):
    root = _parse(tmp_path, aoi, layers)
    bldg = root.find(f".//{{{SVG_NS}}}g[@id='BLDG-FOOTPRINT']")
    assert len(bldg.findall(f"{{{SVG_NS}}}path")) == len(layers["buildings"].gdf)
    assert len(root.find(f".//{{{SVG_NS}}}g[@id='ROAD-CENTRELINE']")) == 2
    assert len(root.find(f".//{{{SVG_NS}}}g[@id='TOPO-CONTOUR']")) > 0
    texts = "".join(
        t.text or "" for t in root.find(f".//{{{SVG_NS}}}g[@id='TEXT-NOTES']").iter(f"{{{SVG_NS}}}text")
    )
    assert "test-site" in texts and "ODbL" in texts and "100 m" in texts


def test_svg_paths_inside_viewbox(tmp_path, aoi, layers):
    root = _parse(tmp_path, aoi, layers)
    vx, vy, vw, vh = (float(v) for v in root.get("viewBox").split())
    n = 0
    for p in root.iter(f"{{{SVG_NS}}}path"):
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", p.get("d"))]
        for x, y in zip(nums[0::2], nums[1::2], strict=True):
            assert vx <= x <= vx + vw and vy <= y <= vy + vh
            n += 1
    assert n > 0


def test_svg_building_with_hole_uses_evenodd(tmp_path, aoi, layers):
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    holed = Polygon(
        box(cx - 20, cy - 20, cx + 20, cy + 20).exterior.coords,
        [box(cx - 5, cy - 5, cx + 5, cy + 5).exterior.coords],
    )
    layers["buildings"].gdf = gpd.GeoDataFrame({"height_m": [5.0]}, geometry=[holed], crs=aoi.crs)
    root = _parse(tmp_path, aoi, layers)
    path = root.find(f".//{{{SVG_NS}}}g[@id='BLDG-FOOTPRINT']/{{{SVG_NS}}}path")
    assert path.get("fill-rule") == "evenodd"
    assert path.get("d").count("M") == 2
