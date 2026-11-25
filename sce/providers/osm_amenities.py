"""Amenity / point-of-interest provider, backed by OpenStreetMap.

Every feature is reduced to a centroid point in the AOI's metric CRS. The
`category` vocabulary is deliberately small: downstream access metrics report
how many distinct CATEGORIES are reachable, not raw POI counts, so a street
with fifty identical convenience stores should not look richer than one with
five different amenity types.
"""

from __future__ import annotations

import osmnx as ox
import pandas as pd

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._overpass import configure_osmnx, with_overpass_fallback

TAGS: dict[str, object] = {
    "amenity": True,
    "shop": True,
    "public_transport": True,
    "railway": ["station", "halt", "tram_stop", "subway_entrance"],
    "healthcare": True,
    "leisure": True,
}

_AMENITY_MAP: dict[str, str] = {
    "restaurant": "food",
    "cafe": "food",
    "fast_food": "food",
    "bar": "food",
    "pub": "food",
    "food_court": "food",
    "ice_cream": "food",
    "biergarten": "food",
    "school": "education",
    "university": "education",
    "college": "education",
    "kindergarten": "education",
    "library": "education",
    "driving_school": "education",
    "language_school": "education",
    "hospital": "health",
    "clinic": "health",
    "pharmacy": "health",
    "dentist": "health",
    "doctors": "health",
    "veterinary": "health",
    "bus_station": "transport",
    "ferry_terminal": "transport",
    "taxi": "transport",
    "parking": "transport",
    "bicycle_parking": "transport",
    "charging_station": "transport",
    "fuel": "transport",
    "townhall": "civic",
    "courthouse": "civic",
    "police": "civic",
    "fire_station": "civic",
    "post_office": "civic",
    "community_centre": "civic",
    "place_of_worship": "civic",
    "embassy": "civic",
    "social_facility": "civic",
    "public_building": "civic",
    "cinema": "leisure",
    "theatre": "leisure",
    "nightclub": "leisure",
    "arts_centre": "leisure",
    "casino": "leisure",
    "marketplace": "retail",
}

_LEISURE_MAP: dict[str, str] = {
    "fitness_centre": "leisure",
    "sports_centre": "leisure",
    "swimming_pool": "leisure",
    "playground": "leisure",
    "park": "leisure",
    "golf_course": "leisure",
}


def _classify(row: pd.Series) -> str:
    if isinstance(row.get("shop"), str):
        return "retail"
    if isinstance(row.get("healthcare"), str) or row.get("healthcare") is True:
        return "health"
    if isinstance(row.get("public_transport"), str) or isinstance(row.get("railway"), str):
        return "transport"
    amenity = row.get("amenity")
    if isinstance(amenity, str) and amenity in _AMENITY_MAP:
        return _AMENITY_MAP[amenity]
    leisure = row.get("leisure")
    if isinstance(leisure, str) and leisure in _LEISURE_MAP:
        return _LEISURE_MAP[leisure]
    return "other"


class OsmAmenitiesProvider(Provider):
    name = "osm_amenities"
    layer = "amenities"
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
            raise RuntimeError(f"osm_amenities: Overpass query failed: {exc}") from exc

        if gdf is None or len(gdf) == 0:
            raise RuntimeError("osm_amenities: no amenity features returned for AOI")

        gdf["category"] = gdf.apply(_classify, axis=1)
        gdf = gdf.reset_index()

        gdf_proj = aoi.to_metric(gdf)
        gdf_proj = gdf_proj[~gdf_proj.geometry.is_empty & gdf_proj.geometry.notna()]
        gdf_proj["geometry"] = gdf_proj.geometry.centroid
        gdf_clipped = aoi.clip(gdf_proj)

        source = Source(
            name="OpenStreetMap contributors (via Overpass API)",
            url="https://www.openstreetmap.org/copyright",
            licence="ODbL 1.0",
            licence_url="https://opendatacommons.org/licenses/odbl/1-0/",
            note=(
                "Amenity/shop/transport/healthcare/leisure points queried with osmnx "
                "features_from_polygon, reduced to centroids"
            ),
            commercial_ok=True,
        )

        n_categories = gdf_clipped["category"].nunique() if len(gdf_clipped) else 0
        coverage = min(n_categories / 8.0, 1.0)

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            gdf=gdf_clipped,
            sources=[source],
            coverage=coverage,
            degraded=False,
            notes=[],
        )


REGISTRY.register(OsmAmenitiesProvider())
