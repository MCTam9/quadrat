"""Land-use / land-cover-ish polygon provider, backed by OpenStreetMap.

Coverage here is deliberately unforgiving: the fraction of the AOI that OSM
tags at all is the honest headline, not something a provider should paper
over with a plausible-looking default.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
from shapely import make_valid
from shapely.ops import unary_union

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ..vocab import landuse_class
from ._overpass import configure_osmnx, register_feature_tags, shared_features

TAGS: dict[str, object] = {
    "landuse": True,
    "leisure": ["park", "garden", "pitch"],
    "natural": ["water", "wood", "scrub"],
}

register_feature_tags("landuse", TAGS)


def _classify(row: pd.Series) -> str:
    return landuse_class(row)


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
            gdf = shared_features(aoi.geometry_wgs84, TAGS)
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

        return self.summarise(
            LayerResult(layer=self.layer, provider=self.name, gdf=gdf_clipped, sources=[source]), aoi
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        """Coverage = union area of the polygons over the square's area."""
        geoms = [] if result.gdf is None else [make_valid(g) for g in result.gdf.geometry if g is not None]
        union = unary_union(geoms) if geoms else None
        area = float(union.area) if union is not None else 0.0
        coverage = min(area / float(aoi.area_m2), 1.0) if aoi.area_m2 else 0.0
        low = coverage < 0.5
        findings = (
            [
                f"only {coverage:.0%} of the AOI carries a landuse/leisure/natural tag in OSM; "
                "the remainder is genuinely unmapped, not implied to be any particular class"
            ]
            if low
            else []
        )
        return replace(result, coverage=coverage, degraded=low, findings=findings)


REGISTRY.register(OsmLanduseProvider())
