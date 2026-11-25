"""Land-use / land-cover-ish polygon provider, backed by OpenStreetMap.

Coverage here is deliberately unforgiving: the fraction of the AOI that OSM
tags at all is the honest headline, not something a provider should paper
over with a plausible-looking default.
"""

from __future__ import annotations

import osmnx as ox
import pandas as pd
from shapely import make_valid
from shapely.ops import unary_union

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._overpass import configure_osmnx, with_overpass_fallback

TAGS: dict[str, object] = {
    "landuse": True,
    "leisure": ["park", "garden", "pitch"],
    "natural": ["water", "wood", "scrub"],
}

_CLASS_MAP: dict[str, dict[str, str]] = {
    "landuse": {
        "residential": "residential",
        "commercial": "commercial",
        "retail": "retail",
        "industrial": "industrial",
        "railway": "transport",
        "cemetery": "other",
        "farmland": "green",
        "farmyard": "green",
        "forest": "green",
        "grass": "green",
        "meadow": "green",
        "orchard": "green",
        "vineyard": "green",
        "recreation_ground": "green",
        "allotments": "green",
        "religious": "institutional",
        "education": "institutional",
        "institutional": "institutional",
        "governmental": "institutional",
        "flowerbed": "green",
        "village_green": "green",
        "military": "other",
        "quarry": "other",
        "brownfield": "other",
        "construction": "other",
        "garages": "other",
    },
    "leisure": {
        "park": "green",
        "garden": "green",
        "pitch": "green",
    },
    "natural": {
        "water": "water",
        "wood": "green",
        "scrub": "green",
    },
}


def _classify(row: pd.Series) -> str:
    for key, mapping in _CLASS_MAP.items():
        value = row.get(key)
        if isinstance(value, str) and value in mapping:
            return mapping[value]
    return "other"


class OsmLanduseProvider(Provider):
    name = "osm_landuse"
    layer = "landuse"
    licence = "ODbL 1.0"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        configure_osmnx(cache)

        try:
            gdf = with_overpass_fallback(ox.features.features_from_polygon, aoi.geometry_wgs84, tags=TAGS)
        except Exception as exc:
            raise RuntimeError(f"osm_landuse: Overpass query failed: {exc}") from exc

        if gdf is None or len(gdf) == 0:
            raise RuntimeError("osm_landuse: no landuse features returned for AOI")

        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if len(gdf) == 0:
            raise RuntimeError("osm_landuse: no polygonal landuse features for AOI")

        gdf["class"] = gdf.apply(_classify, axis=1)
        gdf = gdf.reset_index()

        gdf_proj = aoi.to_metric(gdf)
        gdf_proj["geometry"] = gdf_proj["geometry"].apply(make_valid)
        gdf_clipped = aoi.clip(gdf_proj)
        gdf_clipped = gdf_clipped[~gdf_clipped.geometry.is_empty]

        union = unary_union([make_valid(g) for g in gdf_clipped.geometry])
        coverage = float(union.area) / float(aoi.area_m2) if aoi.area_m2 else 0.0
        coverage = min(coverage, 1.0)

        source = Source(
            name="OpenStreetMap contributors (via Overpass API)",
            url="https://www.openstreetmap.org/copyright",
            licence="ODbL 1.0",
            licence_url="https://opendatacommons.org/licenses/odbl/1-0/",
            note=(
                "Land-use polygons queried with osmnx features_from_polygon over landuse/leisure/natural tags"
            ),
            commercial_ok=True,
        )

        degraded = coverage < 0.5
        notes = (
            []
            if not degraded
            else [
                f"only {coverage:.0%} of the AOI carries a landuse/leisure/natural tag in OSM; "
                "the remainder is genuinely unmapped, not implied to be any particular class"
            ]
        )

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            gdf=gdf_clipped,
            sources=[source],
            coverage=coverage,
            degraded=degraded,
            notes=notes,
        )


REGISTRY.register(OsmLanduseProvider())
