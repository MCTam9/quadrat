"""Building-fabric and block-grain metrics.

Parcel grain is not open data globally — cadastral parcels are behind paywalls
or simply undigitised in most of the world OSM covers well. Block area
(the polygon enclosed by the street network) is the proxy this module reports
instead: it is always derivable from the same street layer every other metric
already uses, at the cost of being coarser than a parcel and of including
whatever mix of parcels, alleys and setbacks sits inside each block.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import numpy as np
from shapely import make_valid
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize

from ..aoi import AOI, assert_metric_crs
from ..types import LayerResult

MIN_BLOCK_AREA_M2 = 500.0
LEVEL_HEIGHT_M = 3.0
FSI_COVERAGE_THRESHOLD = 0.40


def _valid_union_area(geoms) -> tuple[float, BaseGeometry | None]:
    """`make_valid` every geometry, union, THEN take area.

    Summing per-feature areas double-counts anywhere footprints overlap
    (common in dense blocks with sliver duplicates or party-wall buildings
    traced twice), which is how ground space index climbs past 1.0 — the
    most visible possible error on the sheet.
    """
    valid = [make_valid(g) for g in geoms if g is not None and not g.is_empty]
    if not valid:
        return 0.0, None
    import shapely

    union = shapely.union_all(valid)
    return float(union.area), union


def _as_polygons(geom):
    """Flatten whatever `make_valid` returned into plain polygons.

    `make_valid` may hand back a MultiPolygon or a GeometryCollection, neither
    of which has `.exterior`. Reaching for it is an AttributeError that kills
    the whole fabric metric on any site with a self-touching block, which is
    most real cities.
    """
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        out = []
        for part in geom.geoms:
            out.extend(_as_polygons(part))
        return out
    return []


def _block_segments(streets_layer, graph):
    """Line segments to polygonise into blocks.

    Uses the provider's edge geometry when present, falling back to straight
    node-to-node lines from the graph.
    """
    from shapely.geometry import LineString

    gdf = getattr(streets_layer, "gdf", None)
    if gdf is not None and len(gdf) and gdf.geometry.notna().any():
        segments = [g for g in gdf.geometry if g is not None and not g.is_empty]
        if segments:
            return segments

    undirected = nx.Graph(graph.to_undirected())
    xs = nx.get_node_attributes(undirected, "x")
    ys = nx.get_node_attributes(undirected, "y")
    pairs = [[(xs[u], ys[u]), (xs[v], ys[v])] for u, v in undirected.edges() if u in xs and v in ys]
    return [LineString(pts) for pts in pairs if pts[0] != pts[1]]


def _height_source_shares(gdf) -> dict[str, float]:
    """Share of buildings per height source (sce.vocab.HEIGHT_SOURCE ids), summing to 1.

    A building without a finite height counts as "unknown" whatever its tag
    says, so the shares describe what FSI actually used.
    """
    from ..vocab import HEIGHT_SOURCE_IDS

    n = len(gdf)
    counts = dict.fromkeys(HEIGHT_SOURCE_IDS, 0)
    heights = gdf["height_m"] if "height_m" in gdf.columns else None
    sources = gdf["height_source"] if "height_source" in gdf.columns else None
    for i in range(n):
        h = heights.iloc[i] if heights is not None else None
        src = sources.iloc[i] if sources is not None else None
        try:
            known = h is not None and np.isfinite(float(h)) and float(h) > 0
        except (TypeError, ValueError):
            known = False
        key = src if known and isinstance(src, str) and src in counts and src != "unknown" else "unknown"
        if known and key == "unknown":
            key = "height"
        counts[key] += 1
    return {k: (v / n if n else 0.0) for k, v in counts.items()}


def fabric_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    buildings = layers["buildings"]
    assert_metric_crs(buildings.gdf.crs if buildings.gdf is not None else None, where="fabric_metrics")

    result: dict[str, Any] = {}
    gdf = buildings.gdf

    if gdf is None or len(gdf) == 0:
        result.update(
            {
                "gsi": 0.0,
                "building_count": 0,
                "height_source_shares": {},
                "footprint_area_median_m2": None,
                "footprint_area_iqr_m2": None,
                "fsi": None,
                "fsi_coverage": 0.0,
                "fsi_source": "no buildings layer",
            }
        )
    else:
        footprint_union_area, _ = _valid_union_area(gdf.geometry.values)
        result["gsi"] = footprint_union_area / aoi.area_m2 if aoi.area_m2 else None
        result["building_count"] = len(gdf)
        result["height_source_shares"] = _height_source_shares(gdf)

        areas = gdf.geometry.apply(lambda g: make_valid(g).area if g is not None else np.nan).dropna()
        if len(areas):
            q1, med, q3 = np.percentile(areas, [25, 50, 75])
            result["footprint_area_median_m2"] = float(med)
            result["footprint_area_iqr_m2"] = float(q3 - q1)
        else:
            result["footprint_area_median_m2"] = None
            result["footprint_area_iqr_m2"] = None

        coverage = buildings.coverage if buildings.coverage is not None else 0.0
        result["fsi_coverage"] = coverage
        if coverage > FSI_COVERAGE_THRESHOLD and "height_m" in gdf.columns:
            heights = gdf["height_m"].astype(float)
            storeys = heights / LEVEL_HEIGHT_M
            per_building_area = gdf.geometry.apply(lambda g: make_valid(g).area if g is not None else 0.0)
            floor_area = float((per_building_area * storeys.fillna(0.0)).sum())
            result["fsi"] = floor_area / aoi.area_m2 if aoi.area_m2 else None
            lidar = "height_source" in gdf.columns and (gdf["height_source"] == "lidar").any()
            result["fsi_source"] = (
                "building heights (OSM height/levels tags, gaps measured from EA LiDAR)"
                if lidar
                else "building heights (OSM height/levels tags)"
            )
        else:
            ghsl = layers.get("building_height")
            ghsl_mean_height = (ghsl.data or {}).get("mean_height_m") if ghsl is not None else None
            if ghsl_mean_height is not None:
                storeys = ghsl_mean_height / LEVEL_HEIGHT_M
                floor_area = footprint_union_area * storeys
                result["fsi"] = floor_area / aoi.area_m2 if aoi.area_m2 else None
                result["fsi_source"] = (
                    f"GHSL GHS-BUILT-H R2023A mean net building height ({ghsl_mean_height:.1f} m), "
                    f"fallback because OSM height coverage {coverage:.2f} is below "
                    f"{FSI_COVERAGE_THRESHOLD:.2f}"
                )
            else:
                result["fsi"] = None
                result["fsi_source"] = (
                    f"height coverage {coverage:.2f} below {FSI_COVERAGE_THRESHOLD:.2f} threshold"
                )

    streets = layers.get("streets")
    graph = (streets.data or {}).get("graph") if streets is not None else None
    if streets is not None and graph is not None and graph.number_of_edges() > 0:
        assert_metric_crs(graph.graph.get("crs"), where="fabric_metrics.blocks")
        # Prefer the street layer's real edge geometry over straight lines
        # between node coordinates: chording a curved street closes blocks in
        # the wrong place and quietly shrinks every block it touches.
        segments = _block_segments(streets, graph)
        blocks = list(polygonize(segments))
        aoi_boundary = aoi.geometry.boundary
        kept_areas = []
        for block in blocks:
            for piece in _as_polygons(make_valid(block)):
                if piece.is_empty or piece.area < MIN_BLOCK_AREA_M2:
                    continue
                # A block clipped by the AOI edge is only partly present, so
                # counting it would drag the median down toward the frame.
                if piece.intersects(aoi_boundary):
                    continue
                kept_areas.append(piece.area)
        result["block_count"] = len(kept_areas)
        if kept_areas:
            kept_ha = np.array(kept_areas) / 10_000.0
            q1, med, q3 = np.percentile(kept_ha, [25, 50, 75])
            result["block_area_median_ha"] = float(med)
            result["block_area_iqr_ha"] = float(q3 - q1)
        else:
            result["block_area_median_ha"] = None
            result["block_area_iqr_ha"] = None
    else:
        result["block_count"] = None
        result["block_area_median_ha"] = None
        result["block_area_iqr_ha"] = None
        result["block_area_source"] = "no street network available to polygonise blocks"

    return result


fabric_metrics.REQUIRES = ("buildings",)
