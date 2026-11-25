"""Street network provider, backed by OpenStreetMap via osmnx 2.x."""

from __future__ import annotations

import osmnx as ox

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._overpass import configure_osmnx, with_overpass_fallback

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


class OsmStreetsProvider(Provider):
    """The full public right-of-way network ("all_public"), projected once.

    Downstream metrics (orientation entropy, intersection density, access)
    reuse the same projected graph via `LayerResult.data["graph"]` instead of
    re-querying Overpass, since only two concurrent Overpass slots exist.
    """

    name = "osm_streets"
    layer = "streets"
    licence = "ODbL 1.0"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        configure_osmnx(cache)

        try:
            graph = with_overpass_fallback(
                ox.graph.graph_from_polygon,
                aoi.geometry_wgs84,
                network_type="all_public",
                simplify=True,
                retain_all=True,
                truncate_by_edge=True,
            )
        except Exception as exc:
            raise RuntimeError(f"osm_streets: Overpass query failed: {exc}") from exc

        if graph.number_of_edges() == 0:
            raise RuntimeError("osm_streets: empty graph returned for AOI")

        graph_proj = ox.projection.project_graph(graph, to_crs=aoi.crs)
        edges = ox.convert.graph_to_gdfs(graph_proj, nodes=False, edges=True)
        edges = edges.reset_index()
        edges_clipped = aoi.clip(edges)

        source = Source(
            name="OpenStreetMap contributors (via Overpass API)",
            url="https://www.openstreetmap.org/copyright",
            licence="ODbL 1.0",
            licence_url="https://opendatacommons.org/licenses/odbl/1-0/",
            note="Street network queried with osmnx graph_from_polygon(network_type='all_public')",
            commercial_ok=True,
        )

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            gdf=edges_clipped,
            data={"graph": graph_proj},
            sources=[source],
            coverage=None,
            degraded=False,
            notes=[],
        )


REGISTRY.register(OsmStreetsProvider())
