"""Cut a smaller square out of layers already fetched for a larger one.

The web app fetches a padded square once (the slow part: Overpass, tiles)
and then re-analyses whatever square the user drags inside it. Re-fetching
per drag would take tens of seconds; clipping takes well under one.

Contract: the inner AOI must share the outer AOI's CRS (build it with
`AOI.from_point(..., crs=outer.crs)`), and must lie inside the outer square.
Only geometry is cut here; every derived figure (coverage, mean height,
elevation summary, findings) is recomputed by the owning provider's
`summarise`, the same code that ran at fetch, so a
metric never sees a number that belongs to a different area.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pyproj import CRS

from .aoi import AOI
from .types import LayerResult


class ClipOutsideError(ValueError):
    """The inner square is not fully inside the fetched square; fetch again."""


def contains(outer: AOI, inner: AOI, tol_m: float = 0.5) -> bool:
    """True when `inner` lies within `outer` (same CRS), to a small tolerance."""
    if CRS.from_user_input(outer.crs) != CRS.from_user_input(inner.crs):
        return False
    return outer.geometry.buffer(tol_m).contains(inner.geometry)


def _clip_graph(graph: Any, inner: AOI) -> Any:
    """Truncate a projected osmnx graph to the inner square, by edge, as the provider does."""
    import osmnx as ox

    try:
        return ox.truncate.truncate_graph_polygon(graph, inner.geometry, truncate_by_edge=True)
    except ValueError:
        # osmnx raises when nothing survives; an empty graph is the honest answer.
        return graph.subgraph([]).copy()


def _clip_one(layer: str, result: LayerResult, inner: AOI) -> LayerResult:
    """Cut the geometry to `inner`; the owning provider re-summarises it for that square."""
    import sce.providers  # noqa: F401  (registers the providers so REGISTRY is populated)

    from .registry import REGISTRY

    gdf = inner.clip(result.gdf) if result.gdf is not None else None
    raster = result.raster.window(inner) if result.raster is not None else None
    data = result.data
    if layer == "streets" and data and data.get("graph") is not None:
        data = {**data, "graph": _clip_graph(data["graph"], inner)}
    clipped = replace(result, gdf=gdf, raster=raster, data=data)
    provider = REGISTRY.provider(result.provider)
    if provider is None:
        return replace(clipped, findings=[])
    return provider.summarise(clipped, inner)


def clip_layers(layers: dict[str, LayerResult], outer: AOI, inner: AOI) -> dict[str, LayerResult]:
    """Layers for `inner`, derived from layers fetched for `outer`.

    Layers that are not spatial (climate) pass through unchanged: they were
    fetched for the outer centre, which is within a kilometre or two.
    """
    if not contains(outer, inner):
        raise ClipOutsideError(f"{inner.name} is not inside the fetched square {outer.name}")
    out: dict[str, LayerResult] = {}
    for name, result in layers.items():
        if result is None:
            continue
        if result.gdf is None and result.raster is None:
            out[name] = result
            continue
        out[name] = _clip_one(name, result, inner)
    return out
