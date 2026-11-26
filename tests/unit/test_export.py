"""Export layer tests against synthetic fixtures. Zero network."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import ezdxf
import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, Polygon, box

from sce.aoi import AOI
from sce.export.attribution import generate_attribution
from sce.export.dossier import write_dossier
from sce.export.dxf import write_dxf
from sce.export.gpkg import write_gpkg
from sce.export.qml import write_qml_styles
from sce.raster import SiteRaster
from sce.registry import Registry
from sce.types import LayerResult, Provider, Source


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


@pytest.fixture
def metrics() -> dict[str, dict]:
    return {
        "density": {"ground_space_index": 0.12, "ground_space_index_coverage": 1.0},
        "connectivity": {"orientation_order": 1.0},
    }


# -- gpkg ----------------------------------------------------------------


def test_write_gpkg_roundtrip(tmp_path, aoi, layers, metrics):
    out = write_gpkg(tmp_path / "site.gpkg", layers, aoi, metrics=metrics)
    assert out.exists()

    aoi_back = gpd.read_file(out, layer="aoi")
    assert len(aoi_back) == 1
    assert aoi_back.crs.to_epsg() == aoi.crs.to_epsg()

    buildings_back = gpd.read_file(out, layer="buildings")
    assert len(buildings_back) == len(layers["buildings"].gdf)
    assert buildings_back.crs.to_epsg() == aoi.crs.to_epsg()
    # list/dict columns must have survived as strings, not crashed the write.
    assert buildings_back["tags"].apply(lambda v: isinstance(v, str)).all()

    streets_back = gpd.read_file(out, layer="streets")
    assert len(streets_back) == len(layers["streets"].gdf)

    landuse_back = gpd.read_file(out, layer="landuse")
    assert len(landuse_back) == len(layers["landuse"].gdf)


def test_write_gpkg_no_reserved_columns(tmp_path, aoi, layers):
    gdf = layers["buildings"].gdf.copy()
    gdf["fid"] = [1, 2]
    layers = dict(layers)
    layers["buildings"] = LayerResult(layer="buildings", provider="synthetic", gdf=gdf)
    out = write_gpkg(tmp_path / "site2.gpkg", layers, aoi)
    back = gpd.read_file(out, layer="buildings")
    assert "fid_attr" in back.columns


def test_write_gpkg_drops_all_null_columns(tmp_path, aoi, layers):
    gdf = layers["buildings"].gdf.copy()
    gdf["empty_col"] = [None, None]
    layers = dict(layers)
    layers["buildings"] = LayerResult(layer="buildings", provider="synthetic", gdf=gdf)
    out = write_gpkg(tmp_path / "site3.gpkg", layers, aoi)
    back = gpd.read_file(out, layer="buildings")
    assert "empty_col" not in back.columns


def test_write_gpkg_attributes_present(tmp_path, aoi, layers, metrics):
    out = write_gpkg(tmp_path / "site4.gpkg", layers, aoi, metrics=metrics)
    import pyogrio

    layer_names = [name for name, _ in pyogrio.list_layers(out)]
    sidecar = out.with_suffix(out.suffix + ".attributes.json")
    assert "attributes" in layer_names or sidecar.exists()


def _write(tmp_path, frames):
    from sce.export.gpkg_writer import write_layers

    return write_layers(tmp_path / "w.gpkg", frames)


def test_gpkg_header_and_spatial_index(tmp_path, aoi, layers):
    import sqlite3

    import pyogrio

    out = write_gpkg(tmp_path / "idx.gpkg", layers, aoi)
    con = sqlite3.connect(out)
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47
        assert con.execute("PRAGMA user_version").fetchone()[0] == 10400
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
        assert "rtree_buildings_geom" in tables
        assert con.execute("SELECT COUNT(*) FROM rtree_buildings_geom").fetchone()[0] == len(
            layers["buildings"].gdf
        )
    finally:
        con.close()
    info = pyogrio.read_info(out, layer="buildings")
    assert info["features"] == len(layers["buildings"].gdf)
    assert info["geometry_type"] == "Polygon"


def test_gpkg_empty_layer(tmp_path, aoi):
    import pyogrio

    empty = gpd.GeoDataFrame({"a": []}, geometry=[], crs=aoi.crs)
    out = _write(tmp_path, {"empty": empty})
    assert pyogrio.read_info(out, layer="empty")["features"] == 0
    assert len(gpd.read_file(out, layer="empty")) == 0


def test_gpkg_mixed_nulls(tmp_path, aoi):
    gdf = gpd.GeoDataFrame(
        {
            "i": [1, None, 3],
            "f": [1.5, np.nan, 2.5],
            "s": ["a", None, "c"],
            "b": [True, False, True],
        },
        geometry=[box(0, 0, 1, 1), None, box(2, 2, 3, 3)],
        crs=aoi.crs,
    )
    gdf["i"] = gdf["i"].astype("Int64")
    back = gpd.read_file(_write(tmp_path, {"t": gdf}), layer="t")
    assert back["f"].isna().tolist() == [False, True, False]
    assert back["s"].isna().tolist() == [False, True, False]
    assert back["i"].isna().tolist() == [False, True, False]
    assert back.geometry.isna().tolist() == [False, True, False]
    assert back["b"].tolist() == [True, False, True]


def test_gpkg_multipolygon_and_mixed_types(tmp_path, aoi):
    from shapely.geometry import MultiPolygon

    multi = MultiPolygon([box(0, 0, 1, 1), box(5, 5, 6, 6)])
    gdf = gpd.GeoDataFrame({"k": [1, 2]}, geometry=[multi, box(9, 9, 10, 10)], crs=aoi.crs)
    back = gpd.read_file(_write(tmp_path, {"m": gdf}), layer="m")
    assert back.geometry.iloc[0].equals(multi)
    assert back.geometry.iloc[1].equals(box(9, 9, 10, 10))


def test_gpkg_non_ascii_text(tmp_path, aoi):
    gdf = gpd.GeoDataFrame(
        {"name": ["Zürich", "東京", "Ōsaka \u2013 café"]}, geometry=[box(0, 0, 1, 1)] * 3, crs=aoi.crs
    )
    back = gpd.read_file(_write(tmp_path, {"n": gdf}), layer="n")
    assert back["name"].tolist() == gdf["name"].tolist()


def test_gpkg_attribute_only_table(tmp_path):
    import pandas as pd
    import pyogrio

    df = pd.DataFrame({"kind": ["metric", "metric"], "value": [1.0, None]})
    out = _write(tmp_path, {"attributes": df})
    assert ("attributes", None) in [(n, g) for n, g in pyogrio.list_layers(out)]
    back = pyogrio.read_dataframe(out, layer="attributes")
    assert back["kind"].tolist() == ["metric", "metric"]
    assert back["value"].isna().tolist() == [False, True]


@pytest.mark.parametrize("epsg", [32642, 27700, 4326])
def test_gpkg_crs_roundtrip(tmp_path, epsg):
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[box(0, 0, 1, 1)], crs=f"EPSG:{epsg}")
    back = gpd.read_file(_write(tmp_path, {"c": gdf}), layer="c")
    assert back.crs == gdf.crs


# -- qml -------------------------------------------------------------------


def test_write_qml_styles(tmp_path, aoi, layers):
    gpkg_path = tmp_path / "site.gpkg"
    write_gpkg(gpkg_path, layers, aoi)
    qml_paths = write_qml_styles(gpkg_path, layers)
    assert qml_paths
    names = {p.stem.rsplit("_", 1)[-1] for p in qml_paths}
    assert {"aoi", "buildings", "streets", "landuse"} <= names
    for p in qml_paths:
        assert p.exists()
        root = ET.parse(p).getroot()
        assert root.tag == "qgis"
        assert root.find("renderer-v2") is not None


def test_qml_landuse_is_categorized(tmp_path, aoi, layers):
    gpkg_path = tmp_path / "site.gpkg"
    qml_paths = write_qml_styles(gpkg_path, layers)
    landuse_qml = next(p for p in qml_paths if p.stem.endswith("_landuse"))
    root = ET.parse(landuse_qml).getroot()
    renderer = root.find("renderer-v2")
    assert renderer.get("type") == "categorizedSymbol"
    categories = renderer.find("categories").findall("category")
    assert len(categories) >= 2


# -- dxf ---------------------------------------------------------------


def test_write_dxf_layers_and_counts(tmp_path, aoi, layers):
    out = write_dxf(tmp_path / "site.dxf", layers, aoi)
    assert out.exists()

    doc = ezdxf.readfile(out)
    layer_names = {layer.dxf.name for layer in doc.layers}
    for expected in (
        "SITE-BOUNDARY",
        "BLDG-FOOTPRINT",
        "ROAD-CENTRELINE",
        "LANDUSE",
        "TOPO-CONTOUR",
        "TEXT-NOTES",
    ):
        assert expected in layer_names

    msp = doc.modelspace()
    boundary = [e for e in msp if e.dxf.layer == "SITE-BOUNDARY"]
    buildings = [e for e in msp if e.dxf.layer == "BLDG-FOOTPRINT"]
    streets = [e for e in msp if e.dxf.layer == "ROAD-CENTRELINE"]
    landuse = [e for e in msp if e.dxf.layer == "LANDUSE"]
    contours = [e for e in msp if e.dxf.layer == "TOPO-CONTOUR"]
    text_notes = [e for e in msp if e.dxf.layer == "TEXT-NOTES"]

    assert len(boundary) == 1
    assert len(buildings) == len(layers["buildings"].gdf)  # no holes in fixtures
    assert len(streets) == len(layers["streets"].gdf)
    assert len(landuse) == len(layers["landuse"].gdf)
    assert len(contours) > 0
    assert len(text_notes) > 0

    assert doc.header["$INSUNITS"] == ezdxf.units.M

    licence_text = " ".join(e.dxf.text for e in text_notes)
    assert "ODbL" in licence_text or "Open Database" in licence_text


def test_dxf_100m_edge_measures_100(tmp_path, aoi):
    minx, miny = 0.0, 0.0
    square = box(minx, miny, minx + 100.0, miny + 100.0)
    small_aoi = AOI(
        name="unit-square",
        geometry=square,
        crs=aoi.crs,
        centroid_lonlat=aoi.centroid_lonlat,
        radius_m=50.0,
    )
    out = write_dxf(tmp_path / "square.dxf", {}, small_aoi)
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    boundary = next(e for e in msp if e.dxf.layer == "SITE-BOUNDARY")
    points = list(boundary.get_points("xy"))
    edge_length = ((points[1][0] - points[0][0]) ** 2 + (points[1][1] - points[0][1]) ** 2) ** 0.5
    assert edge_length == pytest.approx(100.0, abs=1e-6)


def test_dxf_multipolygon_building_with_hole(tmp_path, aoi):
    from shapely.geometry import MultiPolygon

    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    outer = box(cx - 20, cy - 20, cx + 20, cy + 20)
    hole = box(cx - 5, cy - 5, cx + 5, cy + 5)
    with_hole = Polygon(outer.exterior, [hole.exterior])
    other = box(cx + 100, cy + 100, cx + 110, cy + 110)
    multi = MultiPolygon([with_hole, other])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[multi], crs=aoi.crs)
    layers = {"buildings": LayerResult(layer="buildings", provider="synthetic", gdf=gdf)}
    out = write_dxf(tmp_path / "hole.dxf", layers, aoi)
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    buildings = [e for e in msp if e.dxf.layer == "BLDG-FOOTPRINT"]
    # exterior + hole for with_hole, plus exterior for other = 3 polylines
    assert len(buildings) == 3


def test_dxf_no_terrain_no_crash(tmp_path, aoi, buildings_gdf):
    layers = {"buildings": LayerResult(layer="buildings", provider="synthetic", gdf=buildings_gdf)}
    out = write_dxf(tmp_path / "no_terrain.dxf", layers, aoi)
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    contours = [e for e in msp if e.dxf.layer == "TOPO-CONTOUR"]
    assert contours == []


# -- dossier -------------------------------------------------------------


def test_write_dossier(tmp_path, aoi, layers, metrics):
    out = write_dossier(
        tmp_path / "dossier.json",
        aoi,
        layers,
        metrics,
        assessment={"coverage": {"landuse": 0.12}, "degraded": True, "warnings": ["low coverage on landuse"]},
    )
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["aoi"]["crs"] == aoi.epsg
    assert payload["metrics"]["density"]["ground_space_index"] == 0.12
    assert "buildings" in payload["layers"]
    assert payload["layers"]["buildings"]["features"] == 2
    names = {s["name"] for s in payload["sources"]}
    assert "synthetic-osm" in names
    assert "synthetic-dem" in names
    assert payload["warnings"] == ["low coverage on landuse"]


def test_write_dossier_deterministic(tmp_path, aoi, layers, metrics):
    out1 = write_dossier(tmp_path / "d1.json", aoi, layers, metrics)
    out2 = write_dossier(tmp_path / "d2.json", aoi, layers, metrics)
    p1 = json.loads(out1.read_text())
    p2 = json.loads(out2.read_text())
    p1.pop("generated_at")
    p2.pop("generated_at")
    assert p1 == p2


def test_write_dossier_no_git_tolerated(tmp_path, aoi, layers, metrics, monkeypatch):
    import subprocess as sp

    def fail(*args, **kwargs):
        raise FileNotFoundError("no git")

    monkeypatch.setattr(sp, "run", fail)
    out = write_dossier(tmp_path / "dossier.json", aoi, layers, metrics)
    payload = json.loads(out.read_text())
    assert payload["git_sha"] is None


# -- attribution -----------------------------------------------------------


class _FakeProvider(Provider):
    def __init__(self, name, layer, licence, commercial_ok=True):
        self.name = name
        self.layer = layer
        self.licence = licence
        self.commercial_ok = commercial_ok


def test_generate_attribution(tmp_path):
    registry = Registry()
    registry.register(_FakeProvider("osm-buildings", "buildings", "ODbL"))
    registry.register(_FakeProvider("copernicus-dem", "terrain", "CC-BY-4.0"))
    registry.register(_FakeProvider("fabdem", "terrain", "FABDEM licence", commercial_ok=False))

    out = generate_attribution(registry, tmp_path / "ATTRIBUTION.md")
    text = out.read_text()
    assert "ODbL" in text
    assert "CC-BY-4.0" in text
    assert "osm-buildings" in text
    assert "fabdem" in text
    assert "non-commercial only" in text
    assert "Open Database Licence" in text
    assert "share-alike" in text.lower() or "share alike" in text.lower()


def test_generate_attribution_no_osm(tmp_path):
    registry = Registry()
    registry.register(_FakeProvider("copernicus-dem", "terrain", "CC-BY-4.0"))
    out = generate_attribution(registry, tmp_path / "ATTRIBUTION.md")
    text = out.read_text()
    assert "ODbL" not in text
