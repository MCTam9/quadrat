"""Access/walkability metric tests against synthetic street graphs.

Zero network: every graph here is built by hand with networkx, never osmnx,
so the numbers are analytically known rather than snapshotted.

The reach-ratio numbers below follow from the fact that `_reach_ratio` walks
the graph metric (`ego_graph(..., distance="length")`), not the Euclidean
metric. A 4-connected grid graph with only horizontal/vertical edges makes
graph distance the Manhattan (L1) distance, so the set of nodes within
`WALK_RADIUS_M` forms a diamond (an L1 ball) with vertices exactly at
(+-R, 0) and (0, +-R) when R is a multiple of the grid spacing. That diamond
is a rhombus with both diagonals of length 2R, so its area is
(2R * 2R) / 2 = 2R^2, against a circle of area pi * R^2 -- giving an exact
ratio of 2/pi, independent of the grid spacing chosen.
"""

from __future__ import annotations

import itertools
import math

import networkx as nx
import pytest
from shapely.geometry import Point

from sce.aoi import AOI
from sce.metrics.access import TRANSPORT_CATEGORIES, WALK_RADIUS_M, access_metrics
from sce.types import LayerResult

try:
    import geopandas as gpd
except ImportError:  # pragma: no cover - geopandas is a hard dependency of sce
    gpd = None


def _aoi() -> AOI:
    return AOI.from_point(-0.1, 51.5, 1500.0, name="access-test")


def _centre(aoi: AOI) -> tuple[float, float]:
    c = aoi.geometry.centroid
    return c.x, c.y


def _empty_graph(aoi: AOI) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.graph["crs"] = aoi.crs
    return g


def _grid_graph(aoi: AOI, half_extent: float, spacing: float) -> nx.MultiDiGraph:
    """A fully 4-connected grid graph centred on the AOI centroid."""
    cx, cy = _centre(aoi)
    g = nx.MultiDiGraph()
    g.graph["crs"] = aoi.crs
    n = int(half_extent / spacing)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            g.add_node((i, j), x=cx + i * spacing, y=cy + j * spacing)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if (i + 1, j) in g:
                g.add_edge((i, j), (i + 1, j), length=spacing)
                g.add_edge((i + 1, j), (i, j), length=spacing)
            if (i, j + 1) in g:
                g.add_edge((i, j), (i, j + 1), length=spacing)
                g.add_edge((i, j + 1), (i, j), length=spacing)
    return g


def _line_graph(aoi: AOI, half_count: int, spacing: float) -> nx.MultiDiGraph:
    """A single dead-straight cul-de-sac chain: every node collinear."""
    cx, cy = _centre(aoi)
    g = nx.MultiDiGraph()
    g.graph["crs"] = aoi.crs
    for i in range(-half_count, half_count + 1):
        g.add_node(i, x=cx + i * spacing, y=cy)
    ids = sorted(g.nodes)
    for a, b in itertools.pairwise(ids):
        g.add_edge(a, b, length=spacing)
        g.add_edge(b, a, length=spacing)
    return g


def _streets_layer(graph: nx.MultiDiGraph) -> LayerResult:
    return LayerResult(layer="streets", provider="synthetic", gdf=None, data={"graph": graph})


def _amenities_layer(aoi: AOI, points: list[tuple[float, float, str]]) -> LayerResult:
    cx, cy = _centre(aoi)
    geoms = [Point(cx + dx, cy + dy) for dx, dy, _ in points]
    categories = [cat for _, _, cat in points]
    gdf = gpd.GeoDataFrame({"category": categories}, geometry=geoms, crs=aoi.crs)
    return LayerResult(layer="amenities", provider="synthetic", gdf=gdf)


# ---------------------------------------------------------------------------
# walk_reach_ratio_10min
# ---------------------------------------------------------------------------


def test_perfect_grid_gives_high_reach_ratio():
    aoi = _aoi()
    graph = _grid_graph(aoi, half_extent=2000.0, spacing=100.0)
    layers = {"streets": _streets_layer(graph)}
    result = access_metrics(layers, aoi)
    expected = 2.0 / math.pi
    assert result["walk_reach_ratio_10min"] == pytest.approx(expected, rel=1e-6)


def test_cul_de_sac_chain_gives_much_lower_reach_ratio():
    aoi = _aoi()
    # A chain long enough that +-WALK_RADIUS_M is fully inside it.
    graph = _line_graph(aoi, half_count=40, spacing=50.0)
    layers = {"streets": _streets_layer(graph)}
    result = access_metrics(layers, aoi)
    # Every reached node is collinear: the convex hull is a degenerate
    # LineString with zero area, so the ratio is exactly zero.
    assert result["walk_reach_ratio_10min"] == pytest.approx(0.0)

    grid_graph = _grid_graph(aoi, half_extent=2000.0, spacing=100.0)
    grid_result = access_metrics({"streets": _streets_layer(grid_graph)}, aoi)
    assert result["walk_reach_ratio_10min"] < grid_result["walk_reach_ratio_10min"]


def test_empty_graph_returns_none_not_raises():
    aoi = _aoi()
    graph = _empty_graph(aoi)
    layers = {"streets": _streets_layer(graph)}
    result = access_metrics(layers, aoi)
    assert result["walk_reach_ratio_10min"] is None
    assert result["amenity_category_count_10min"] is None


def test_disconnected_single_node_returns_none_not_raises():
    aoi = _aoi()
    cx, cy = _centre(aoi)
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = aoi.crs
    graph.add_node(0, x=cx, y=cy)
    graph.add_node(1, x=cx + 5000.0, y=cy + 5000.0)  # far away, disconnected
    layers = {"streets": _streets_layer(graph)}
    result = access_metrics(layers, aoi)
    assert result["walk_reach_ratio_10min"] is None


# ---------------------------------------------------------------------------
# amenity_category_count_10min counts distinct categories, not raw POIs
# ---------------------------------------------------------------------------


def test_amenity_category_count_counts_categories_not_points():
    aoi = _aoi()
    graph = _grid_graph(aoi, half_extent=1000.0, spacing=100.0)
    points = [(10.0 * i, 0.0, "food") for i in range(10)] + [(0.0, 10.0, "education")]
    layers = {"streets": _streets_layer(graph), "amenities": _amenities_layer(aoi, points)}
    result = access_metrics(layers, aoi)
    assert result["amenity_category_count_10min"] == 2


def test_amenity_category_count_ignores_points_outside_walk_radius():
    aoi = _aoi()
    graph = _grid_graph(aoi, half_extent=2000.0, spacing=100.0)
    points = [(0.0, 0.0, "food"), (0.0, WALK_RADIUS_M + 500.0, "civic")]
    layers = {"streets": _streets_layer(graph), "amenities": _amenities_layer(aoi, points)}
    result = access_metrics(layers, aoi)
    assert result["amenity_category_count_10min"] == 1


# ---------------------------------------------------------------------------
# nearest_transit_distance_m
# ---------------------------------------------------------------------------


def test_nearest_transit_distance_measured_correctly():
    aoi = _aoi()
    graph = _grid_graph(aoi, half_extent=1000.0, spacing=100.0)
    points = [(0.0, 300.0, "transport"), (0.0, 900.0, "transport"), (500.0, 0.0, "food")]
    layers = {"streets": _streets_layer(graph), "amenities": _amenities_layer(aoi, points)}
    result = access_metrics(layers, aoi)
    assert result["nearest_transit_distance_m"] == pytest.approx(300.0)


def test_nearest_transit_distance_is_none_without_transport_amenity():
    aoi = _aoi()
    graph = _grid_graph(aoi, half_extent=1000.0, spacing=100.0)
    points = [(0.0, 300.0, "food"), (0.0, 900.0, "civic")]
    layers = {"streets": _streets_layer(graph), "amenities": _amenities_layer(aoi, points)}
    result = access_metrics(layers, aoi)
    assert result["nearest_transit_distance_m"] is None


def test_transport_categories_constant_covers_vocabulary_transport_term():
    # CONTRIBUTING.md fixes the amenities vocabulary as food/retail/education/
    # health/transport/civic/leisure/other; "transport" must be recognised.
    assert "transport" in TRANSPORT_CATEGORIES


def test_requires_attribute_declared():
    assert access_metrics.REQUIRES == ("streets",)
