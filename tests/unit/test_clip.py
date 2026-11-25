"""clip_layers: analysing a square cut from a padded fetch must match a direct summary.

One property, per layer type: `clip_layers({layer: provider.summarise(outer_result, outer)})`
gives the same coverage, degraded flag, findings and derived data as
`provider.summarise(<the same data built for the inner square>, inner)`.
"""

from __future__ import annotations

import math
from dataclasses import replace

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, Point, box

import sce.providers  # noqa: F401  (registers providers)
from sce.aoi import AOI
from sce.clip import ClipOutsideError, clip_layers, contains
from sce.metrics.fabric import fabric_metrics
from sce.raster import SiteRaster, inside_mask
from sce.registry import REGISTRY
from sce.types import LayerResult


@pytest.fixture
def outer() -> AOI:
    return AOI.from_point(-0.1, 51.5, 1500.0, name="padded")


@pytest.fixture
def inner(outer: AOI) -> AOI:
    return AOI.from_point(-0.1, 51.5, 300.0, name="site", crs=outer.crs)


def _buildings(aoi: AOI) -> gpd.GeoDataFrame:
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    geoms = [
        box(cx - 50, cy - 50, cx - 30, cy - 30),  # inside the inner square
        box(cx + 100, cy + 100, cx + 130, cy + 130),  # inside
        box(cx + 1000, cy + 1000, cx + 1040, cy + 1040),  # outside inner, inside outer
    ]
    return gpd.GeoDataFrame(
        {"height_m": [9.0, np.nan, 30.0], "height_source": ["height", "", "height"]},
        geometry=geoms,
        crs=aoi.crs,
    )


def _grid(aoi: AOI, res: float) -> tuple[Affine, tuple[int, int]]:
    minx, miny, maxx, maxy = aoi.bounds_metric
    cols, rows = math.ceil((maxx - minx) / res), math.ceil((maxy - miny) / res)
    return Affine(res, 0, minx, 0, -res, maxy), (rows, cols)


def _centres(shape, t: Affine) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.indices(shape)
    return t.c + (cols + 0.5) * t.a, t.f + (rows + 0.5) * t.e


def _masked(arr: np.ndarray, t: Affine, aoi: AOI, fill) -> np.ndarray:
    out = arr.copy()
    out[~inside_mask(out.shape, t, aoi)] = fill
    return out


def _assert_same(a: LayerResult, b: LayerResult) -> None:
    assert a.coverage == pytest.approx(b.coverage)
    assert a.degraded == b.degraded
    assert a.findings == b.findings


def _clip_via(result: LayerResult, outer: AOI, inner: AOI) -> LayerResult:
    provider = REGISTRY.provider(result.provider)
    assert provider is not None
    return clip_layers({result.layer: provider.summarise(result, outer)}, outer, inner)[result.layer]


def test_inner_shares_crs_and_is_contained(outer, inner):
    assert inner.crs == outer.crs
    assert contains(outer, inner)
    far = AOI.from_point(-0.05, 51.5, 300.0, crs=outer.crs)
    assert not contains(outer, far)


def test_outside_raises(outer):
    far = AOI.from_point(-0.05, 51.5, 300.0, crs=outer.crs)
    with pytest.raises(ClipOutsideError):
        clip_layers({}, outer, far)


def test_buildings_clip_matches_direct(outer, inner):
    full = _buildings(outer)
    clipped = _clip_via(LayerResult("buildings", "osm_buildings", gdf=full), outer, inner)
    direct = REGISTRY.provider("osm_buildings").summarise(
        LayerResult("buildings", "osm_buildings", gdf=inner.clip(full)), inner
    )
    assert len(clipped.gdf) == 2
    assert clipped.coverage == pytest.approx(0.5)
    _assert_same(clipped, direct)


def test_buildings_findings_recomputed_and_in_provenance(outer, inner):
    sparse = _buildings(outer)
    sparse.loc[0, "height_m"] = np.nan  # no inner building has a known height now
    out = _clip_via(LayerResult("buildings", "overture_buildings", gdf=sparse), outer, inner)
    assert out.coverage == 0.0 and out.degraded
    assert out.findings == ["fewer than half of buildings have a known height"]
    assert out.provenance()["notes"] == [*out.notes, *out.findings]


def test_landuse_clip_matches_direct(outer, inner):
    cx, cy = inner.geometry.centroid.x, inner.geometry.centroid.y
    # One polygon covering the west half of the inner square, plus a big one outside it.
    gdf = gpd.GeoDataFrame(
        {"class": ["residential", "green"]},
        geometry=[box(cx - 300, cy - 300, cx, cy + 300), box(cx + 400, cy - 1400, cx + 1400, cy + 1400)],
        crs=outer.crs,
    )
    provider = REGISTRY.provider("osm_landuse")
    outer_sum = provider.summarise(LayerResult("landuse", "osm_landuse", gdf=gdf), outer)
    assert outer_sum.degraded and outer_sum.findings  # the padded-area figure must not leak
    clipped = clip_layers({"landuse": outer_sum}, outer, inner)["landuse"]
    direct = provider.summarise(LayerResult("landuse", "osm_landuse", gdf=inner.clip(gdf)), inner)
    assert clipped.coverage == pytest.approx(0.5, abs=0.02)
    _assert_same(clipped, direct)


def test_landcover_clip_matches_direct(outer, inner):
    from sce.providers.landcover_worldcover import CLASSES

    res_m = 10.0
    t, shape = _grid(outer, res_m)
    xs, ys = _centres(shape, t)
    cx = inner.geometry.centroid.x

    def classes(xs, ys, geom):
        # Built-up site with a no-data strip in its west; trees elsewhere.
        arr = np.full(xs.shape, 10, dtype=np.uint8)
        site = np.array([geom.contains(Point(x, y)) for x, y in zip(xs.ravel(), ys.ravel(), strict=True)])
        site = site.reshape(xs.shape)
        arr[site] = 50
        arr[site & (xs < cx - 100)] = 0
        return arr

    lc = LayerResult(
        "landcover",
        "esa_worldcover",
        raster=SiteRaster.from_array(classes(xs, ys, inner.geometry), t, outer.crs, square=outer, nodata=0),
        data={"class_colours": {"x": "#000"}},
    )
    clipped = _clip_via(lc, outer, inner)

    it, ishape = _grid(inner, res_m)
    ixs, iys = _centres(ishape, it)
    direct_raster = SiteRaster.from_array(
        _masked(classes(ixs, iys, inner.geometry), it, inner, 0), it, outer.crs, square=inner, nodata=0
    )
    direct = REGISTRY.provider("esa_worldcover").summarise(
        LayerResult("landcover", "esa_worldcover", raster=direct_raster, data=lc.data), inner
    )
    fractions = clipped.data["class_fractions"]
    assert set(fractions) == {CLASSES[50], "Unclassified/no data"}
    assert sum(fractions.values()) == pytest.approx(1.0)
    assert clipped.coverage == pytest.approx(1.0 - fractions["Unclassified/no data"])
    for key, value in direct.data["class_fractions"].items():
        assert fractions[key] == pytest.approx(value, abs=0.03)
    assert clipped.coverage == pytest.approx(direct.coverage, abs=0.03)
    assert clipped.data["class_colours"] == {"x": "#000"}


def test_ghsl_clip_matches_direct(outer, inner):
    res_m = 100.0
    t, shape = _grid(outer, res_m)
    xs, _ = _centres(shape, t)
    cx = outer.geometry.centroid.x
    arr = np.where(xs < cx, 12.0, np.nan).astype(np.float32)
    arr[xs < cx - 600] = 0.0  # covered, but zero height is not averaged
    raster = SiteRaster.from_array(_masked(arr, t, outer, np.nan), t, outer.crs, square=outer, nodata=np.nan)
    res = LayerResult("building_height", "ghsl_building_height", raster=raster)
    clipped = _clip_via(res, outer, inner)
    direct = REGISTRY.provider("ghsl_building_height").summarise(
        replace(res, raster=raster.window(inner)), inner
    )
    _assert_same(clipped, direct)
    assert clipped.data["mean_height_m"] == pytest.approx(12.0)
    assert clipped.coverage == pytest.approx(0.5, abs=0.2)


def test_lidar_ndsm_clip_uses_building_like_threshold_and_ignores_corners(outer, inner):
    from sce.providers.height_ea_lidar import BUILDING_LIKE_MIN_M

    assert BUILDING_LIKE_MIN_M == 2.5
    res_m = 5.0
    t, shape = _grid(outer, res_m)
    xs, ys = _centres(shape, t)
    cx, cy = inner.geometry.centroid.x, inner.geometry.centroid.y
    arr = np.full(shape, 1.0, dtype=np.float32)  # finite ground, below the threshold
    arr[(xs > cx) & (ys > cy)] = 10.0  # one quadrant of buildings
    raster = SiteRaster.from_array(
        _masked(arr, t, outer, np.nan), t, outer.crs, square=outer, nodata=float("nan"), kind="ndsm"
    )
    res = LayerResult("building_height", "ea_lidar_ndsm", raster=raster, data={"kind": "ndsm"})
    out = _clip_via(res, outer, inner)
    assert out.raster.kind == "ndsm" and out.data["kind"] == "ndsm"
    # Mean over cells > 2.5 m only; a mean over cells > 0 would sit well below 10.
    assert out.data["mean_height_m"] == pytest.approx(10.0)
    # Every cell inside the square is finite: masked bbox corners are not missing LiDAR.
    assert np.isnan(out.raster.array[0, 0])
    assert out.coverage == pytest.approx(1.0)
    assert not out.degraded
    direct = REGISTRY.provider("ea_lidar_ndsm").summarise(replace(res, raster=raster.window(inner)), inner)
    _assert_same(out, direct)
    assert out.data["mean_height_m"] == pytest.approx(direct.data["mean_height_m"])


def test_terrain_clip_matches_direct(outer, inner):
    res_m = 30.0
    t, shape = _grid(outer, res_m)
    xs, _ = _centres(shape, t)
    arr = _masked(((xs - xs.min()) / 10.0).astype(np.float32), t, outer, np.nan)
    raster = SiteRaster.from_array(arr, t, outer.crs, square=outer, nodata=np.nan)
    res = LayerResult(
        "terrain", "copernicus_terrain", raster=raster, data={"terrain_model": "DSM"}, coverage=1.0
    )
    clipped = _clip_via(res, outer, inner)
    direct = REGISTRY.provider("copernicus_terrain").summarise(
        replace(res, raster=raster.window(inner)), inner
    )
    sub = clipped.raster.array
    assert clipped.data["terrain_model"] == "DSM"
    for key in ("min_elevation_m", "max_elevation_m", "mean_elevation_m"):
        assert clipped.data[key] == pytest.approx(direct.data[key])
    assert clipped.data["min_elevation_m"] == pytest.approx(float(np.nanmin(sub)))
    assert clipped.data["max_elevation_m"] < float(np.nanmax(arr))


def test_fabric_matches_direct(outer, inner):
    """GSI from a clip equals GSI computed on the inner square's own data."""
    full = _buildings(outer)
    via_clip = fabric_metrics(
        clip_layers({"buildings": LayerResult("buildings", "osm_buildings", gdf=full)}, outer, inner), inner
    )
    direct = fabric_metrics(
        {"buildings": LayerResult("buildings", "osm_buildings", gdf=inner.clip(full))}, inner
    )
    assert via_clip["gsi"] == pytest.approx(direct["gsi"])


def test_raster_windowed_to_inner_bounds(outer, inner):
    minx, miny, maxx, maxy = outer.bounds_metric
    res = 30.0
    cols, rows = int((maxx - minx) / res), int((maxy - miny) / res)
    arr = np.arange(rows * cols, dtype=float).reshape(rows, cols)
    t = Affine(res, 0, minx, 0, -res, maxy)
    layers = {
        "terrain": LayerResult(
            "terrain",
            "copernicus_terrain",
            raster=SiteRaster.from_array(arr, t, outer.crs, square=outer, nodata=np.nan),
        )
    }
    out = clip_layers(layers, outer, inner)["terrain"]
    sub = out.raster.array
    iminx, iminy, imaxx, imaxy = inner.bounds_metric
    # floor/ceil to whole cells: up to one extra cell at each edge.
    assert sub.shape[0] == pytest.approx((imaxy - iminy) / res, abs=2)
    assert sub.shape[1] == pytest.approx((imaxx - iminx) / res, abs=2)
    # Corners of the window fall outside the rotated (true-north) square.
    assert np.isnan(sub[0, 0]) and np.isnan(sub[-1, -1])
    assert np.isfinite(sub[sub.shape[0] // 2, sub.shape[1] // 2])
    ox_, oy_ = out.raster.transform.c, out.raster.transform.f
    assert iminx - res <= ox_ <= iminx
    assert imaxy <= oy_ <= imaxy + res
    assert out.data["min_elevation_m"] == pytest.approx(float(np.nanmin(sub)))


def test_climate_passes_through(outer, inner):
    climate = LayerResult("climate", "fake", data={"t": 1})
    assert clip_layers({"climate": climate}, outer, inner)["climate"] is climate


def test_unknown_provider_clips_geometry_only(outer, inner):
    lu = LayerResult("landuse", "fake", gdf=_buildings(outer), coverage=0.3, findings=["stale"])
    out = clip_layers({"landuse": lu}, outer, inner)["landuse"]
    assert len(out.gdf) == 2 and out.findings == []


def test_streets_graph_truncated(outer, inner):
    cx, cy = inner.geometry.centroid.x, inner.geometry.centroid.y
    g = nx.MultiDiGraph(crs=outer.crs)
    g.add_node(1, x=cx, y=cy)
    g.add_node(2, x=cx + 100, y=cy)
    g.add_node(3, x=cx + 1200, y=cy)
    g.add_edge(1, 2, length=100.0)
    g.add_edge(2, 3, length=1100.0)
    edges = gpd.GeoDataFrame(
        geometry=[LineString([(cx, cy), (cx + 100, cy)]), LineString([(cx + 100, cy), (cx + 1200, cy)])],
        crs=outer.crs,
    )
    layers = {"streets": LayerResult("streets", "osm_streets", gdf=edges, data={"graph": g})}
    out = clip_layers(layers, outer, inner)["streets"]
    assert 1 in out.data["graph"].nodes
    assert out.gdf.total_bounds[2] <= inner.bounds_metric[2] + 1e-6
