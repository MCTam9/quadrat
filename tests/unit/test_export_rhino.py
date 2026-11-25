"""Rhino/Grasshopper `.3dm` export, checked by writing then reading back with
`rhino3dm.File3dm.Read` — the same round-trip a designer's Rhino session does.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, MultiPolygon, Polygon, box

rhino3dm = pytest.importorskip("rhino3dm")

from sce.aoi import AOI  # noqa: E402
from sce.export.rhino import write_3dm  # noqa: E402
from sce.raster import SiteRaster  # noqa: E402
from sce.types import LayerResult, Source  # noqa: E402


@pytest.fixture
def aoi() -> AOI:
    return AOI.from_point(lon=-0.1, lat=51.5, radius_m=500.0, name="test-site")


@pytest.fixture
def buildings_gdf(aoi: AOI) -> gpd.GeoDataFrame:
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    known = box(cx - 110, cy - 110, cx - 90, cy - 90)  # 20x20, height 10 -> massing
    unknown = box(cx + 90, cy + 90, cx + 120, cy + 120)  # 30x30, no height -> footprint only
    outer = box(cx - 200, cy - 200, cx - 150, cy - 150)
    hole = box(cx - 190, cy - 190, cx - 160, cy - 160)
    with_hole = Polygon(outer.exterior, [hole.exterior])
    return gpd.GeoDataFrame(
        {"height_m": [10.0, None, 15.0]},
        geometry=[known, unknown, with_hole],
        crs=aoi.crs,
    )


@pytest.fixture
def streets_gdf(aoi: AOI) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = aoi.bounds_metric
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    return gpd.GeoDataFrame(
        {"highway": ["primary"]}, geometry=[LineString([(minx, cy), (maxx, cy)])], crs=aoi.crs
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
    array = (xs - minx) / 100.0  # a tilted plane, 1 m rise per 100 m eastward
    return SiteRaster.from_array(array, transform, aoi.crs, square=aoi)


@pytest.fixture
def layers(aoi, buildings_gdf, streets_gdf, terrain_raster) -> dict[str, LayerResult]:
    src = Source(name="synthetic-osm", url="https://example.invalid", licence="ODbL")
    return {
        "buildings": LayerResult(
            layer="buildings", provider="synthetic", gdf=buildings_gdf, sources=[src], coverage=1.0
        ),
        "streets": LayerResult(
            layer="streets", provider="synthetic", gdf=streets_gdf, sources=[src], coverage=1.0
        ),
        "terrain": LayerResult(
            layer="terrain",
            provider="synthetic",
            raster=terrain_raster,
            sources=[Source(name="synthetic-dem", url="https://example.invalid", licence="CC-BY-4.0")],
            coverage=1.0,
        ),
    }


def _by_layer(doc):
    grouped: dict[str, list] = {name: [] for name in [layer.Name for layer in doc.Layers]}
    for obj in doc.Objects:
        name = doc.Layers[obj.Attributes.LayerIndex].Name
        grouped.setdefault(name, []).append(obj)
    return grouped


def test_write_3dm_missing_dependency_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "rhino3dm":
            raise ImportError("no module named rhino3dm")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    from sce.export.rhino import write_3dm as write_3dm_reimported

    with pytest.raises(ImportError, match="rhino"):
        write_3dm_reimported("/tmp/unused.3dm", {}, None)


def test_write_3dm_layers_units_and_counts(tmp_path, aoi, layers):
    out = write_3dm(tmp_path / "site.3dm", layers, aoi)
    assert out.exists()

    doc = rhino3dm.File3dm.Read(str(out))
    layer_names = {layer.Name for layer in doc.Layers}
    for expected in ("SITE-BOUNDARY", "BLDG-MASSING", "BLDG-FOOTPRINT", "ROAD-CENTRELINE", "TOPO-CONTOUR"):
        assert expected in layer_names

    assert doc.Settings.ModelUnitSystem == rhino3dm.UnitSystem.Meters

    grouped = _by_layer(doc)
    assert len(grouped["SITE-BOUNDARY"]) == 1
    assert len(grouped["ROAD-CENTRELINE"]) == 1
    assert len(grouped["TOPO-CONTOUR"]) > 0

    # known-height building + the with-hole building both become extrusions;
    # the unknown-height building stays a flat footprint curve.
    assert len(grouped["BLDG-MASSING"]) == 2
    assert len(grouped["BLDG-FOOTPRINT"]) == 1
    for obj in grouped["BLDG-MASSING"]:
        assert obj.Geometry.ObjectType == rhino3dm.ObjectType.Extrusion
    for obj in grouped["BLDG-FOOTPRINT"]:
        assert obj.Geometry.ObjectType == rhino3dm.ObjectType.Curve


def test_write_3dm_known_building_height_matches_extrusion(tmp_path, aoi, layers):
    out = write_3dm(tmp_path / "site.3dm", layers, aoi)
    doc = rhino3dm.File3dm.Read(str(out))
    grouped = _by_layer(doc)

    heights = sorted(
        round(obj.Geometry.GetBoundingBox().Max.Z - obj.Geometry.GetBoundingBox().Min.Z, 6)
        for obj in grouped["BLDG-MASSING"]
    )
    assert heights == [10.0, 15.0]


def test_write_3dm_boundary_edge_length(tmp_path, aoi):
    out = write_3dm(tmp_path / "empty.3dm", {}, aoi)
    doc = rhino3dm.File3dm.Read(str(out))
    grouped = _by_layer(doc)
    boundary = grouped["SITE-BOUNDARY"][0]
    polyline = boundary.Geometry.ToPolyline()
    p0, p1 = polyline.PointAt(0), polyline.PointAt(1)
    edge = ((p1.X - p0.X) ** 2 + (p1.Y - p0.Y) ** 2) ** 0.5
    assert edge == pytest.approx(1000.0, rel=1e-6)  # radius 500 m -> a 1000 m square edge


def test_write_3dm_multipolygon_with_hole(tmp_path, aoi):
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    outer = box(cx - 20, cy - 20, cx + 20, cy + 20)
    hole = box(cx - 5, cy - 5, cx + 5, cy + 5)
    with_hole = Polygon(outer.exterior, [hole.exterior])
    other = box(cx + 100, cy + 100, cx + 110, cy + 110)
    multi = MultiPolygon([with_hole, other])
    gdf = gpd.GeoDataFrame({"height_m": [25.0]}, geometry=[multi], crs=aoi.crs)
    layers = {"buildings": LayerResult(layer="buildings", provider="synthetic", gdf=gdf)}

    out = write_3dm(tmp_path / "hole.3dm", layers, aoi)
    doc = rhino3dm.File3dm.Read(str(out))
    grouped = _by_layer(doc)

    # Both polygon parts of the MultiPolygon get a known height -> two extrusions,
    # one of them (the one with the hole) not a solid box.
    assert len(grouped["BLDG-MASSING"]) == 2
    assert grouped["BLDG-FOOTPRINT"] == []


def test_write_3dm_no_terrain_no_crash(tmp_path, aoi, buildings_gdf):
    layers = {"buildings": LayerResult(layer="buildings", provider="synthetic", gdf=buildings_gdf)}
    out = write_3dm(tmp_path / "no_terrain.3dm", layers, aoi)
    assert out.exists()
