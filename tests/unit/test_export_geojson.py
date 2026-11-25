"""GeoJSON export tests against synthetic fixtures. Zero network."""

from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, Polygon, box

from sce.aoi import AOI
from sce.export.geojson import write_geojson
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
def terrain_raster(aoi: AOI) -> dict:
    minx, miny, maxx, maxy = aoi.bounds_metric
    res = 10.0
    cols = int((maxx - minx) / res)
    rows = int((maxy - miny) / res)
    transform = Affine(res, 0, minx, 0, -res, maxy)
    row_idx, col_idx = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    xs, ys = transform * (col_idx + 0.5, row_idx + 0.5)
    # A tilted plane: elevation rises 1m per 100m eastward. Known slope, known contours.
    array = (xs - minx) / 100.0
    return {"array": array, "transform": transform, "crs": aoi.crs, "nodata": None, "res": (res, res)}


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


def _load(tmp_path, aoi, layers):
    out = write_geojson(tmp_path / "site.geojson", layers, aoi)
    return json.loads(out.read_text())


def _by_layer(fc, name):
    return [f for f in fc["features"] if f["properties"]["layer"] == name]


def _first_coord(geom):
    c = geom["coordinates"]
    while isinstance(c[0], list):
        c = c[0]
    return c


def test_geojson_structure_and_layers(tmp_path, aoi, layers):
    fc = _load(tmp_path, aoi, layers)
    assert fc["type"] == "FeatureCollection"
    assert len(_by_layer(fc, "buildings")) == 2
    assert len(_by_layer(fc, "streets")) == 2
    assert len(_by_layer(fc, "landuse")) == 2
    assert len(_by_layer(fc, "site_boundary")) == 1
    assert fc["sce"]["crs_source"] == aoi.epsg
    assert "synthetic-osm - ODbL" in fc["sce"]["licence"]
    assert fc["sce"]["odbl_notice"]


def test_geojson_coordinates_are_lonlat_near_centre(tmp_path, aoi, layers):
    fc = _load(tmp_path, aoi, layers)
    lon0, lat0 = aoi.centroid_lonlat
    for f in fc["features"]:
        lon, lat = _first_coord(f["geometry"])[:2]
        assert abs(lon - lon0) < 0.02 and abs(lat - lat0) < 0.02
        assert round(lon, 7) == lon and round(lat, 7) == lat


def test_geojson_building_height_and_nan(tmp_path, aoi, layers):
    gdf = layers["buildings"].gdf.copy()
    gdf["height_m"] = [10.0, np.nan]
    gdf["height_source"] = ["osm", "unknown"]
    layers["buildings"].gdf = gdf
    text = tmp_path / "site.geojson"
    fc = _load(tmp_path, aoi, layers)
    assert "NaN" not in text.read_text()
    heights = [f["properties"]["height_m"] for f in _by_layer(fc, "buildings")]
    assert heights == [10.0, None]
    assert _by_layer(fc, "buildings")[0]["properties"]["height_source"] == "osm"


def test_geojson_drops_container_columns(tmp_path, aoi, layers):
    fc = _load(tmp_path, aoi, layers)
    for f in _by_layer(fc, "landuse"):
        assert f["properties"]["class"] in ("residential", "park")
    layers["landuse"].gdf = layers["landuse"].gdf.assign(tags=[{"a": 1}, {"b": 2}], ids=[[1], [2]])
    fc = _load(tmp_path, aoi, layers)
    for f in _by_layer(fc, "landuse"):
        assert "tags" not in f["properties"] and "ids" not in f["properties"]


def test_geojson_contours_for_tilted_plane(tmp_path, aoi, layers):
    fc = _load(tmp_path, aoi, layers)
    contours = _by_layer(fc, "contour")
    assert contours
    assert all(f["geometry"]["type"] == "LineString" for f in contours)
    assert all("elevation_m" in f["properties"] for f in contours)


def test_geojson_without_terrain_has_no_contours(tmp_path, aoi, layers):
    layers.pop("terrain")
    assert _by_layer(_load(tmp_path, aoi, layers), "contour") == []
