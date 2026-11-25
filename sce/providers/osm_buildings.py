"""Building footprint provider, backed by OpenStreetMap via osmnx 2.x."""

from __future__ import annotations

import osmnx as ox
import pandas as pd

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source
from ._buildings import summarise_building_heights
from ._height import height_and_source
from ._overpass import configure_osmnx, with_overpass_fallback


class OsmBuildingsProvider(Provider):
    """Building footprints with a best-effort height, from OSM tags.

    `coverage` is the fraction of footprints with a known height (from either
    the `height` or `building:levels` tag) — this is what gates FSI downstream,
    since an unmapped skyline should not be reported as a confident number.
    """

    name = "osm_buildings"
    layer = "buildings"
    licence = "ODbL 1.0"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        configure_osmnx(cache)

        try:
            gdf = with_overpass_fallback(
                ox.features.features_from_polygon, aoi.geometry_wgs84, tags={"building": True}
            )
        except Exception as exc:
            raise RuntimeError(f"osm_buildings: Overpass query failed: {exc}") from exc

        if gdf is None or len(gdf) == 0:
            raise RuntimeError("osm_buildings: no building features returned for AOI")

        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if len(gdf) == 0:
            raise RuntimeError("osm_buildings: no polygonal building features for AOI")

        height_col = gdf["height"] if "height" in gdf.columns else pd.Series(None, index=gdf.index)
        levels_col = (
            gdf["building:levels"] if "building:levels" in gdf.columns else pd.Series(None, index=gdf.index)
        )
        parsed = [height_and_source(h, lv) for h, lv in zip(height_col, levels_col, strict=False)]
        gdf["height_m"] = [p[0] for p in parsed]
        gdf["height_source"] = [p[1] for p in parsed]

        gdf = gdf.reset_index()
        gdf_proj = aoi.to_metric(gdf)
        gdf_clipped = aoi.clip(gdf_proj)

        source = Source(
            name="OpenStreetMap contributors (via Overpass API)",
            url="https://www.openstreetmap.org/copyright",
            licence="ODbL 1.0",
            licence_url="https://opendatacommons.org/licenses/odbl/1-0/",
            note="Building footprints queried with osmnx features_from_polygon(tags={'building': True})",
            commercial_ok=True,
        )

        return self.summarise(
            LayerResult(layer=self.layer, provider=self.name, gdf=gdf_clipped, sources=[source]), aoi
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        return summarise_building_heights(result)


REGISTRY.register(OsmBuildingsProvider())
