"""Street network morphology metrics.

Deliberately cut from this module: circuity, k_avg, and other whole-graph
telemetry osmnx computes by default. Those describe the graph's topology in
the abstract; they do not tell an urban designer anything about the site that
intersection density, block-scale grain and orientation order do not already
say more directly, and every extra number here is a number someone has to
explain on the sheet.

Orientation order (`phi`) follows Boeing, G. 2019, "Urban Spatial Order:
Street Network Orientation, Configuration, and Entropy", Applied Network
Science 4(1). Entropy is computed over a 36-bin histogram of edge bearings
(`Hmax = ln(36)`, a fully random compass distribution) against the entropy of
a perfect four-way grid (`Hmin = ln(4)`, all mass in the cardinal/ordinal
pair of bins a grid produces), then normalised:

    phi = 1 - ((H - Hmin) / (Hmax - Hmin)) ** 2

A perfect grid has H == Hmin, so phi == 1.0. A uniform, fully random spread of
bearings has H == Hmax, so phi == 0.0.

Bearings are computed directly from the AOI's projected (metric) coordinates,
not by re-projecting the graph back to WGS84 and using osmnx's geodesic
`calculate_bearing`. For an AOI this size (a few km across at most) the two
agree to well under a degree, and working entirely in the metric CRS we
already hold means one fewer reprojection and one fewer place to smuggle in a
degrees/metres mixup.
"""

from __future__ import annotations

import math
from typing import Any

import networkx as nx
import numpy as np
import osmnx as ox

from ..aoi import AOI, assert_metric_crs
from ..types import LayerResult

NUM_BINS = 36
H_MAX = math.log(NUM_BINS)
H_MIN = math.log(4)
CONSOLIDATION_TOLERANCE_M = 10.0


def _planar_bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass bearing (0 = north, clockwise) between two projected points."""
    dx = x2 - x1
    dy = y2 - y1
    return math.degrees(math.atan2(dx, dy)) % 360.0


def _bearing_histogram(graph: nx.MultiDiGraph, num_bins: int = NUM_BINS) -> tuple[np.ndarray, np.ndarray]:
    """36-bin bearing histogram, using the same edge-effect-safe binning osmnx uses.

    Runs on the directed graph as given: two-way streets already appear as a
    reciprocal pair of directed edges, which is what makes a perfect grid's
    histogram land on 4 populated bins (matching `H_MIN`) rather than 2.
    """
    xs = nx.get_node_attributes(graph, "x")
    ys = nx.get_node_attributes(graph, "y")
    bearings = [_planar_bearing(xs[u], ys[u], xs[v], ys[v]) for u, v, k in graph.edges(keys=True) if u != v]
    bearings_arr = np.array(bearings, dtype=float)

    num_split_bins = num_bins * 2
    split_edges = np.linspace(0, 360, num_split_bins + 1)
    split_counts, _ = np.histogram(bearings_arr, bins=split_edges)
    split_counts = np.roll(split_counts, 1)
    bin_counts = (split_counts[::2] + split_counts[1::2]).astype(float)
    bin_centers = split_edges[range(0, num_split_bins - 1, 2)]
    return bin_counts, bin_centers


def street_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    streets = layers["streets"]
    # Check every CRS we were handed before demanding anything else. A provider
    # that forgot to reproject must be rejected here, not after we have already
    # decided the graph is missing and raised a different error.
    if streets.gdf is not None and len(streets.gdf):
        assert_metric_crs(streets.gdf.crs, where="street_metrics[streets.gdf]")
    graph = (streets.data or {}).get("graph")
    if graph is not None:
        assert_metric_crs(graph.graph.get("crs"), where="street_metrics[graph]")
    if graph is None:
        raise ValueError("street_metrics requires layers['streets'].data['graph']")

    area_km2 = aoi.area_m2 / 1e6
    result: dict[str, Any] = {}

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        return {
            "intersection_count": 0,
            "intersection_density_km2": 0.0,
            "street_length_km": 0.0,
            "street_length_density_km_km2": 0.0,
            "segment_length_mean_m": None,
            "segment_length_median_m": None,
            "dead_end_share": None,
            "orientation_entropy_nats": None,
            "orientation_order_phi": None,
            "orientation_bins": [0.0] * NUM_BINS,
            "orientation_bin_centers_deg": list(np.linspace(0, 360, NUM_BINS, endpoint=False) + 5.0),
        }

    consolidated = ox.simplification.consolidate_intersections(
        graph,
        tolerance=CONSOLIDATION_TOLERANCE_M,
        rebuild_graph=False,
        dead_ends=False,
    )
    n_intersections = len(consolidated)
    result["intersection_count"] = n_intersections
    result["intersection_density_km2"] = n_intersections / area_km2 if area_km2 else None

    undirected = ox.convert.to_undirected(graph)
    seg_lengths = np.array(
        [float(d.get("length", 0.0)) for _, _, d in undirected.edges(data=True)], dtype=float
    )
    total_length_km = float(seg_lengths.sum()) / 1000.0
    result["street_length_km"] = total_length_km
    result["street_length_density_km_km2"] = total_length_km / area_km2 if area_km2 else None
    result["segment_length_mean_m"] = float(seg_lengths.mean()) if seg_lengths.size else None
    result["segment_length_median_m"] = float(np.median(seg_lengths)) if seg_lengths.size else None

    spn = ox.stats.count_streets_per_node(graph)
    n_nodes = len(spn)
    dead_ends = sum(1 for count in spn.values() if count <= 1)
    result["dead_end_share"] = dead_ends / n_nodes if n_nodes else None

    bin_counts, bin_centers = _bearing_histogram(graph, NUM_BINS)
    total = bin_counts.sum()
    if total > 0:
        probs = bin_counts / total
        entropy = float(-sum(p * math.log(p) for p in probs if p > 0))
        phi = 1.0 - ((entropy - H_MIN) / (H_MAX - H_MIN)) ** 2
        phi = max(0.0, min(1.0, phi))
    else:
        entropy = None
        phi = None
    result["orientation_entropy_nats"] = entropy
    result["orientation_order_phi"] = phi
    result["orientation_bins"] = bin_counts.tolist()
    result["orientation_bin_centers_deg"] = bin_centers.tolist()

    return result


street_metrics.REQUIRES = ("streets",)
