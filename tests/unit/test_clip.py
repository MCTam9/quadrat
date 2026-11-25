"""clip_layers: analysing a square cut from a padded fetch must match a direct fetch."""

from __future__ import annotations

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, box

from sce.aoi import AOI
from sce.clip import ClipOutsideError, clip_layers, contains
from sce.metrics.fabric import fabric_metrics
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


def test_inner_shares_crs_and_is_contained(outer, inner):
    assert inner.crs == outer.crs
    assert contains(outer, inner)
    far = AOI.from_point(-0.05, 51.5, 300.0, crs=outer.crs)
    assert not contains(outer, far)


def test_outside_raises(outer):
    far = AOI.from_point(-0.05, 51.5, 300.0, crs=outer.crs)
    with pytest.raises(ClipOutsideError):
        clip_layers({}, outer, far)


def test_buildings_clipped_and_coverage_recomputed(outer, inner):
    layers = {"buildings": LayerResult("buildings", "fake", gdf=_buildings(outer), coverage=2 / 3)}
    clipped = clip_layers(layers, outer, inner)
    assert len(clipped["buildings"].gdf) == 2
    assert clipped["buildings"].coverage == pytest.approx(0.5)


def test_fabric_matches_direct(outer, inner):
    """GSI from a clip equals GSI computed on the inner square's own data."""
    full = _buildings(outer)
    via_clip = fabric_metrics(
        clip_layers({"buildings": LayerResult("buildings", "fake", gdf=full)}, outer, inner), inner
    )
    direct = fabric_metrics({"buildings": LayerResult("buildings", "fake", gdf=inner.clip(full))}, inner)
    assert via_clip["gsi"] == pytest.approx(direct["gsi"])


def test_raster_windowed_to_inner_bounds(outer, inner):
    minx, miny, maxx, maxy = outer.bounds_metric
    res = 30.0
    cols, rows = int((maxx - minx) / res), int((maxy - miny) / res)
    arr = np.arange(rows * cols, dtype=float).reshape(rows, cols)
    t = Affine(res, 0, minx, 0, -res, maxy)
    layers = {
        "terrain": LayerResult(
            "terrain", "fake", raster={"array": arr, "transform": t, "crs": outer.crs, "res": (res, res)}
        )
    }
    out = clip_layers(layers, outer, inner)["terrain"]
    sub = out.raster["array"]
    iminx, iminy, imaxx, imaxy = inner.bounds_metric
    # floor/ceil to whole cells: up to one extra cell at each edge.
    assert sub.shape[0] == pytest.approx((imaxy - iminy) / res, abs=2)
    assert sub.shape[1] == pytest.approx((imaxx - iminx) / res, abs=2)
    # Corners of the window fall outside the rotated (true-north) square.
    assert np.isnan(sub[0, 0]) and np.isnan(sub[-1, -1])
    assert np.isfinite(sub[sub.shape[0] // 2, sub.shape[1] // 2])
    ox_, oy_ = out.raster["transform"].c, out.raster["transform"].f
    iminx, _, _, imaxy = inner.bounds_metric
    assert iminx - res <= ox_ <= iminx
    assert imaxy <= oy_ <= imaxy + res
    assert out.data["min_elevation_m"] == pytest.approx(float(np.nanmin(sub)))


def test_climate_passes_through(outer, inner):
    climate = LayerResult("climate", "fake", data={"t": 1})
    assert clip_layers({"climate": climate}, outer, inner)["climate"] is climate


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
    layers = {"streets": LayerResult("streets", "fake", gdf=edges, data={"graph": g})}
    out = clip_layers(layers, outer, inner)["streets"]
    assert 1 in out.data["graph"].nodes
    assert out.gdf.total_bounds[2] <= inner.bounds_metric[2] + 1e-6


def test_landuse_coverage_rejudged_for_inner_square(outer, inner):
    """A padded-area coverage figure must never leak into the inner square's warnings."""
    cx, cy = inner.geometry.centroid.x, inner.geometry.centroid.y
    # One polygon covering the west half of the inner square, plus a big one outside it.
    gdf = gpd.GeoDataFrame(
        {"class": ["residential", "green"]},
        geometry=[box(cx - 300, cy - 300, cx, cy + 300), box(cx + 400, cy - 1400, cx + 1400, cy + 1400)],
        crs=outer.crs,
    )
    stale = ["only 30% of the AOI carries a landuse/leisure/natural tag in OSM; ..."]
    lu = LayerResult("landuse", "fake", gdf=gdf, coverage=0.3, degraded=True, notes=stale)
    out = clip_layers({"landuse": lu}, outer, inner)["landuse"]
    assert out.coverage == pytest.approx(0.5, abs=0.02)
    assert not any("30%" in n for n in out.notes)


def test_landcover_fractions_rejudged_for_inner_square(outer, inner):
    from sce.providers.landcover_worldcover import CLASSES

    minx, miny, maxx, maxy = outer.bounds_metric
    res = 10.0
    cols, rows = int((maxx - minx) / res), int((maxy - miny) / res)
    arr = np.zeros((rows, cols), dtype=np.uint8)
    tree, built = 10, 50
    arr[:, :] = tree
    t = Affine(res, 0, minx, 0, -res, maxy)
    # Inner square is all "built-up"; the rest of the padded area is trees.
    r0, r1 = int((maxy - inner.bounds_metric[3]) / res), int((maxy - inner.bounds_metric[1]) / res)
    c0, c1 = int((inner.bounds_metric[0] - minx) / res), int((inner.bounds_metric[2] - minx) / res)
    arr[r0:r1, c0:c1] = built
    lc = LayerResult(
        "landcover",
        "fake",
        raster={"array": arr, "transform": t, "crs": outer.crs, "nodata": 0, "res": (res, res)},
        data={"class_fractions": {"Tree cover": 0.96}},
        coverage=1.0,
    )
    out = clip_layers({"landcover": lc}, outer, inner)["landcover"]
    assert out.data["class_fractions"][CLASSES[built]] == pytest.approx(1.0, abs=0.01)
    assert out.coverage == pytest.approx(1.0, abs=0.01)
