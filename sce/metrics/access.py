"""Walkability and access metrics from the street and amenity layers.

Amenity CATEGORIES reachable, not raw POI counts, are what this module
reports: a single well-mapped cafe strip can carry hundreds of duplicate
points in OSM while a genuinely mixed-use block gets none of that credit.
Counting distinct categories measures the diversity of what is reachable on
foot, which is closer to what "walkable" is meant to describe than counting
how enthusiastically an area has been surveyed.
"""

from __future__ import annotations

import math
from typing import Any

import networkx as nx

from ..aoi import AOI, assert_metric_crs
from ..types import LayerResult

WALK_RADIUS_M = 800.0  # ~10 minutes at a typical walking pace


def _nearest_node(graph: nx.MultiDiGraph, x: float, y: float) -> int | None:
    best_node, best_dist = None, math.inf
    for node, data in graph.nodes(data=True):
        d = (data["x"] - x) ** 2 + (data["y"] - y) ** 2
        if d < best_dist:
            best_dist, best_node = d, node
    return best_node


def _reach_ratio(graph: nx.MultiDiGraph, centre_node: int) -> float | None:
    try:
        undirected = nx.Graph(graph.to_undirected())
        ego = nx.ego_graph(undirected, centre_node, radius=WALK_RADIUS_M, distance="length")
    except (nx.NetworkXError, KeyError):
        return None
    if ego.number_of_nodes() < 3:
        return None
    points = [(d["x"], d["y"]) for _, d in ego.nodes(data=True)]
    from shapely.geometry import MultiPoint

    hull = MultiPoint(points).convex_hull
    reached_area = hull.area if hull.geom_type == "Polygon" else 0.0
    circle_area = math.pi * WALK_RADIUS_M**2
    return reached_area / circle_area if circle_area else None


# The transport category as the amenities provider emits it. Kept as a module
# constant so a vocabulary change is a one-line edit in one place.
TRANSPORT_CATEGORIES = frozenset({"transport", "public_transport", "transit_stop"})


def access_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    streets = layers["streets"]
    # Check every CRS we were handed before demanding anything else. A provider
    # that forgot to reproject must be rejected here, not after we have already
    # decided the graph is missing and raised a different error.
    if streets.gdf is not None and len(streets.gdf):
        assert_metric_crs(streets.gdf.crs, where="access_metrics[streets.gdf]")
    graph = (streets.data or {}).get("graph")
    if graph is not None:
        assert_metric_crs(graph.graph.get("crs"), where="access_metrics[graph]")
    if graph is None:
        raise ValueError("access_metrics requires layers['streets'].data['graph']")

    result: dict[str, Any] = {}
    centre = aoi.geometry.centroid
    cx, cy = centre.x, centre.y

    if graph.number_of_nodes() == 0:
        result["walk_reach_ratio_10min"] = None
        result["amenity_category_count_10min"] = None
    else:
        centre_node = _nearest_node(graph, cx, cy)
        result["walk_reach_ratio_10min"] = (
            _reach_ratio(graph, centre_node) if centre_node is not None else None
        )

        amenities = layers.get("amenities")
        categories: set[str] = set()
        if amenities is not None and amenities.gdf is not None and len(amenities.gdf):
            assert_metric_crs(amenities.gdf.crs, where="access_metrics.amenities")
            reach = centre.buffer(WALK_RADIUS_M)
            nearby = amenities.gdf[amenities.gdf.geometry.within(reach)]
            col = "category" if "category" in nearby.columns else None
            if col is not None:
                categories = set(nearby[col].dropna().astype(str))
        result["amenity_category_count_10min"] = (
            len(categories) if categories or amenities is not None else None
        )

    transit = layers.get("amenities")
    nearest_transit_m: float | None = None
    if transit is not None and transit.gdf is not None and len(transit.gdf):
        gdf = transit.gdf
        assert_metric_crs(gdf.crs, where="access_metrics.transit")
        col = "category" if "category" in gdf.columns else None
        if col is not None:
            # The amenities provider's vocabulary is fixed in CONTRACT.md:
            # food, retail, education, health, transport, civic, leisure, other.
            # The older names are kept only so a stale fixture still resolves.
            transit_rows = gdf[gdf[col].astype(str).str.lower().isin(TRANSPORT_CATEGORIES)]
            if len(transit_rows):
                nearest_transit_m = float(transit_rows.geometry.distance(centre).min())
    result["nearest_transit_distance_m"] = nearest_transit_m

    return result


access_metrics.REQUIRES = ("streets",)
