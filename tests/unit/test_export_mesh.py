"""Mesh export tests on synthetic fixtures. Zero network."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Polygon, box

from sce.aoi import AOI
from sce.export._georef import local_origin
from sce.export.mesh import write_glb, write_obj
from sce.raster import SiteRaster
from sce.types import LayerResult

trimesh = pytest.importorskip("trimesh")


@pytest.fixture
def aoi() -> AOI:
    return AOI.from_point(lon=-0.1, lat=51.5, radius_m=500.0, name="test-site")


def _terrain(aoi: AOI) -> SiteRaster:
    minx, miny, maxx, maxy = aoi.bounds_metric
    res = 10.0
    cols, rows = int((maxx - minx) / res), int((maxy - miny) / res)
    transform = Affine(res, 0, minx, 0, -res, maxy)
    r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    xs, _ = transform * (c + 0.5, r + 0.5)
    # Rises 1 m per 100 m eastward, from 100 m at the west edge.
    return SiteRaster.from_array(100.0 + (xs - minx) / 100.0, transform, aoi.crs, square=aoi)


def _layers(aoi: AOI, with_terrain: bool = True) -> dict[str, LayerResult]:
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    gdf = gpd.GeoDataFrame(
        {"height_m": [10.0, np.nan]},
        geometry=[box(cx - 110, cy - 110, cx - 90, cy - 90), box(cx + 90, cy + 90, cx + 110, cy + 110)],
        crs=aoi.crs,
    )
    out = {"buildings": LayerResult(layer="buildings", provider="synthetic", gdf=gdf)}
    if with_terrain:
        out["terrain"] = LayerResult(layer="terrain", provider="synthetic", raster=_terrain(aoi))
    return out


def test_glb_named_geometries_and_local_origin(tmp_path, aoi):
    out = write_glb(tmp_path / "s.glb", _layers(aoi), aoi)
    scene = trimesh.load(out)
    assert {"TERRAIN", "BLDG-MASSING", "BLDG-FOOTPRINT"} <= set(scene.geometry)
    for g in scene.geometry.values():
        assert np.abs(g.vertices[:, [0, 2]]).max() < 600  # local origin applied, not UTM magnitudes
    assert scene.metadata["crs"] == aoi.epsg


def test_glb_building_top_is_base_plus_height(tmp_path, aoi):
    scene = trimesh.load(write_glb(tmp_path / "s.glb", _layers(aoi), aoi))
    m = scene.geometry["BLDG-MASSING"]
    # Terrain rises 1 m/100 m eastward from the bbox west edge. The AOI is a
    # true-north square, slightly rotated in UTM, so its bbox is a little wider
    # than 1 km: measure from the bbox, not from a nominal 500 m.
    west = aoi.geometry.centroid.x - aoi.bounds_metric[0]
    base = 100.0 + (west - 110) / 100.0
    ys = m.vertices[:, 1]  # glTF up axis
    assert ys.max() == pytest.approx(base + 10.0, abs=0.1)
    assert ys.min() == pytest.approx(base, abs=0.1)


def test_unknown_height_not_extruded(tmp_path, aoi):
    scene = trimesh.load(write_glb(tmp_path / "s.glb", _layers(aoi), aoi))
    fp = scene.geometry["BLDG-FOOTPRINT"]
    assert np.ptp(fp.vertices[:, 1]) < 0.1
    # lifted 5 cm above the lowest terrain under the footprint (x = +90 from centre)
    west = aoi.geometry.centroid.x - aoi.bounds_metric[0]
    assert fp.vertices[:, 1].min() == pytest.approx(100.0 + (west + 90) / 100.0 + 0.05, abs=0.1)


def test_no_terrain_still_writes_buildings(tmp_path, aoi):
    out = write_glb(tmp_path / "s.glb", _layers(aoi, with_terrain=False), aoi)
    scene = trimesh.load(out)
    assert "TERRAIN" not in scene.geometry
    m = scene.geometry["BLDG-MASSING"]
    assert m.vertices[:, 1].min() == pytest.approx(0.0, abs=1e-3)
    assert m.vertices[:, 1].max() == pytest.approx(10.0, abs=1e-3)


def test_multipolygon_with_hole_and_invalid_footprint(tmp_path, aoi):
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    holed = Polygon(
        box(cx, cy, cx + 40, cy + 40).exterior.coords,
        [box(cx + 10, cy + 10, cx + 30, cy + 30).exterior.coords],
    )
    bowtie = Polygon([(cx - 50, cy), (cx - 30, cy + 20), (cx - 30, cy), (cx - 50, cy + 20)])
    gdf = gpd.GeoDataFrame({"height_m": [8.0, 8.0]}, geometry=[holed, bowtie], crs=aoi.crs)
    layers = {"buildings": LayerResult(layer="buildings", provider="s", gdf=gdf)}
    scene = trimesh.load(write_glb(tmp_path / "h.glb", layers, aoi))
    assert len(scene.geometry["BLDG-MASSING"].faces) > 24  # more than two plain boxes


def test_obj_groups_and_z_up_extent(tmp_path, aoi):
    out = write_obj(tmp_path / "s.obj", _layers(aoi), aoi)
    text = out.read_text()
    for name in ("TERRAIN", "BLDG-MASSING", "BLDG-FOOTPRINT"):
        assert f"o {name}" in text and f"g {name}" in text
    assert out.with_suffix(".mtl").exists()
    top: dict[str, float] = {}
    group = ""
    for line in text.splitlines():
        if line.startswith("o "):
            group = line[2:]
        elif line.startswith("v "):
            top[group] = max(top.get(group, -1e9), float(line.split()[3]))
    # Terrain rises 1 m/100 m eastward from the bbox west edge; the 10 m building
    # starts 110 m west of centre, so its top is base + 10 (Z is up).
    minx, _, maxx, _ = aoi.bounds_metric
    west = aoi.geometry.centroid.x - minx
    # The fixture grid holds whole 10 m cells, so it can stop up to a cell short of maxx.
    assert top["TERRAIN"] == pytest.approx(100.0 + (maxx - minx) / 100.0, abs=0.2)
    assert top["BLDG-MASSING"] == pytest.approx(100.0 + (west - 110) / 100.0 + 10.0, abs=0.15)
    assert top["BLDG-FOOTPRINT"] < top["BLDG-MASSING"]
    xs = [float(line.split()[1]) for line in text.splitlines() if line.startswith("v ")]
    assert max(abs(x) for x in xs) < 600
    assert local_origin(aoi) != (0, 0)
