"""Fabric metrics, checked against analytically known answers.

The overlapping-squares case is the one the contract calls out explicitly:
summing footprint areas instead of unioning them pushes ground space index
past what is physically possible in a dense block.
"""

from __future__ import annotations

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import box

from sce.aoi import AOI, NonMetricCRSError
from sce.metrics.fabric import fabric_metrics
from sce.types import LayerResult


def _aoi(radius: float = 100.0) -> AOI:
    return AOI.from_point(0.0, 51.0, radius, name="fabric")


def test_gsi_uses_union_not_sum_of_overlapping_footprints():
    aoi = _aoi(radius=100.0)
    square_a = box(0, 0, 100, 100)
    square_b = box(50, 50, 150, 150)
    gdf = gpd.GeoDataFrame(
        {"height_m": [9.0, 9.0]}, geometry=[square_a, square_b], crs=aoi.crs
    )
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=1.0)
    layers = {"buildings": buildings}

    result = fabric_metrics(layers, aoi)

    union_area = 100 * 100 + 100 * 100 - 50 * 50
    naive_sum_area = 100 * 100 + 100 * 100
    expected_gsi = union_area / aoi.area_m2
    wrong_gsi = naive_sum_area / aoi.area_m2

    assert result["gsi"] == pytest.approx(expected_gsi)
    assert result["gsi"] != pytest.approx(wrong_gsi)
    assert result["gsi"] < 1.0


def test_fsi_none_below_coverage_threshold():
    aoi = _aoi()
    gdf = gpd.GeoDataFrame(
        {"height_m": [9.0]}, geometry=[box(0, 0, 10, 10)], crs=aoi.crs
    )
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=0.1)
    result = fabric_metrics({"buildings": buildings}, aoi)
    assert result["fsi"] is None
    assert result["fsi_coverage"] == pytest.approx(0.1)
    assert "below" in result["fsi_source"]


def test_fsi_computed_above_coverage_threshold():
    aoi = _aoi()
    gdf = gpd.GeoDataFrame(
        {"height_m": [9.0]}, geometry=[box(0, 0, 10, 10)], crs=aoi.crs
    )
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=0.9)
    result = fabric_metrics({"buildings": buildings}, aoi)
    expected_fsi = (10 * 10 * (9.0 / 3.0)) / aoi.area_m2
    assert result["fsi"] == pytest.approx(expected_fsi)


def test_footprint_median_and_iqr():
    aoi = _aoi()
    squares = [box(0, 0, 10, 10), box(20, 20, 30, 40), box(40, 40, 41, 41)]
    gdf = gpd.GeoDataFrame({"height_m": [9.0, 9.0, 9.0]}, geometry=squares, crs=aoi.crs)
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=1.0)
    result = fabric_metrics({"buildings": buildings}, aoi)
    areas = sorted([100.0, 200.0, 1.0])
    assert result["footprint_area_median_m2"] == pytest.approx(100.0)


def _grid_graph(n: int, spacing: float, crs) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs=crs)
    for i in range(n):
        for j in range(n):
            graph.add_node(i * n + j, x=j * spacing, y=i * spacing)

    def add_edge(u: int, v: int) -> None:
        x1, y1 = graph.nodes[u]["x"], graph.nodes[u]["y"]
        x2, y2 = graph.nodes[v]["x"], graph.nodes[v]["y"]
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        graph.add_edge(u, v, length=length)
        graph.add_edge(v, u, length=length)

    for i in range(n):
        for j in range(n - 1):
            add_edge(i * n + j, i * n + j + 1)
    for i in range(n - 1):
        for j in range(n):
            add_edge(i * n + j, (i + 1) * n + j)
    return graph


def test_block_metrics_drop_slivers_and_edge_blocks():
    aoi = AOI.from_point(0.0, 51.0, 300.0, name="blocks")
    graph = _grid_graph(3, 100.0, aoi.crs)
    for _, data in graph.nodes(data=True):
        data["x"] -= 100.0
        data["y"] -= 100.0
    gdf = gpd.GeoDataFrame({"height_m": [9.0]}, geometry=[box(-140, -140, -130, -130)], crs=aoi.crs)
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=1.0)
    streets = LayerResult(layer="streets", provider="synthetic", data={"graph": graph})
    result = fabric_metrics({"buildings": buildings, "streets": streets}, aoi)
    assert result["block_count"] == 4
    assert result["block_area_median_ha"] == pytest.approx(10000.0 / 10_000.0)
    assert result["block_area_iqr_ha"] == pytest.approx(0.0)


def test_geographic_crs_rejected():
    gdf = gpd.GeoDataFrame({"height_m": [9.0]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    buildings = LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=1.0)
    aoi = _aoi()
    with pytest.raises(NonMetricCRSError):
        fabric_metrics({"buildings": buildings}, aoi)


def test_requires_attribute_declared():
    assert fabric_metrics.REQUIRES == ("buildings",)
