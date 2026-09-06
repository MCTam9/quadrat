"""Street metrics, checked against analytically known answers.

A perfect NxN lattice of streets is the one network whose intersection count,
length density and orientation order can all be worked out by hand: every
bearing lands exactly on 0/90/180/270 degrees, so entropy hits Boeing's
`H_MIN = ln(4)` floor and `phi` must be exactly 1.0.
"""

from __future__ import annotations

import networkx as nx
import pytest

from sce.aoi import AOI, NonMetricCRSError
from sce.metrics.street import street_metrics
from sce.types import LayerResult


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


def _grid_layers(n: int = 6, spacing: float = 200.0):
    extent = (n - 1) * spacing
    aoi = AOI.from_point(0.0, 51.0, extent / 2.0, name="grid")
    graph = _grid_graph(n, spacing, aoi.crs)
    layers = {"streets": LayerResult(layer="streets", provider="synthetic", data={"graph": graph})}
    return layers, aoi


def test_perfect_grid_orientation_order_is_one():
    layers, aoi = _grid_layers()
    result = street_metrics(layers, aoi)
    assert result["orientation_order_phi"] == pytest.approx(1.0, abs=1e-9)
    assert result["orientation_entropy_nats"] == pytest.approx(__import__("math").log(4), abs=1e-9)
    assert sum(result["orientation_bins"]) == pytest.approx(
        sum(1 for _ in layers["streets"].data["graph"].edges())
    )


def test_perfect_grid_known_counts_and_densities():
    layers, aoi = _grid_layers(n=6, spacing=200.0)
    result = street_metrics(layers, aoi)
    assert aoi.area_km2 == pytest.approx(1.0)
    assert result["intersection_count"] == 36
    assert result["intersection_density_km2"] == pytest.approx(36.0)
    assert result["street_length_km"] == pytest.approx(12.0)
    assert result["street_length_density_km_km2"] == pytest.approx(12.0)
    assert result["segment_length_mean_m"] == pytest.approx(200.0)
    assert result["segment_length_median_m"] == pytest.approx(200.0)
    assert result["dead_end_share"] == pytest.approx(0.0)


def test_dead_end_share_counts_degree_one_nodes():
    aoi = AOI.from_point(0.0, 51.0, 100.0, name="stub")
    graph = nx.MultiDiGraph(crs=aoi.crs)
    graph.add_node(0, x=0.0, y=0.0)
    graph.add_node(1, x=100.0, y=0.0)
    graph.add_node(2, x=200.0, y=0.0)
    graph.add_edge(0, 1, length=100.0)
    graph.add_edge(1, 0, length=100.0)
    graph.add_edge(1, 2, length=100.0)
    graph.add_edge(2, 1, length=100.0)
    layers = {"streets": LayerResult(layer="streets", provider="synthetic", data={"graph": graph})}
    result = street_metrics(layers, aoi)
    assert result["dead_end_share"] == pytest.approx(2.0 / 3.0)


def test_empty_graph_returns_zeros_not_crash():
    aoi = AOI.from_point(0.0, 51.0, 100.0, name="empty")
    graph = nx.MultiDiGraph(crs=aoi.crs)
    layers = {"streets": LayerResult(layer="streets", provider="synthetic", data={"graph": graph})}
    result = street_metrics(layers, aoi)
    assert result["intersection_count"] == 0
    assert result["orientation_order_phi"] is None


def test_geographic_crs_is_rejected():
    aoi = AOI.from_point(0.0, 51.0, 500.0, name="grid")
    graph = _grid_graph(3, 0.001, "EPSG:4326")
    layers = {"streets": LayerResult(layer="streets", provider="synthetic", data={"graph": graph})}
    with pytest.raises(NonMetricCRSError):
        street_metrics(layers, aoi)


def test_requires_attribute_declared():
    assert street_metrics.REQUIRES == ("streets",)
