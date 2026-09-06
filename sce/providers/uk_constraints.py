"""Great Britain planning-constraint provider (planning.data.gov.uk).

The "same command, richer where richer data exists" layer: a Conservation
Area block appears on the London sheet and simply does not exist on the
Tashkent or Riyadh one, because `available()` gates this provider to GB.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source

API_URL = "https://www.planning.data.gov.uk/entity.geojson"

# Confirmed live against the API on 2026-09-06 with a London bbox.
DATASETS = ["conservation-area", "article-4-direction-area", "listed-building-outline", "flood-risk-zone"]

LIMIT_PER_DATASET = 500

# A loose bounding box, NOT a coastline or EEZ test: it will pass a centroid
# that sits in the sea west of Ireland or north of the Northern Isles. Good
# enough to gate an availability check; not a substitute for a real boundary.
GB_BBOX = (-8.7, 49.8, 1.8, 61.0)


class UkConstraintsProvider(Provider):
    """Conservation areas, Article 4 directions, listed buildings, flood zones."""

    name = "uk_planning_data"
    layer = "constraints"
    licence = "OGL v3.0"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:  # noqa: ANN001
        lon, lat = aoi.centroid_lonlat
        w, s, e, n = GB_BBOX
        return w <= lon <= e and s <= lat <= n

    def fetch(self, aoi, cache) -> LayerResult:  # noqa: ANN001
        w, s, e, n = aoi.bbox_wgs84
        wkt = f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"

        frames = []
        sources = []
        for dataset in DATASETS:
            params = {
                "dataset": dataset,
                "geometry": wkt,
                "geometry_relation": "intersects",
                "limit": LIMIT_PER_DATASET,
            }
            key = cache.key("planning-data", dataset, round(w, 5), round(s, 5), round(e, 5), round(n, 5))

            def _producer(params=params):
                resp = requests.get(API_URL, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json(), {"url": resp.url}

            payload, meta = cache.get_json(key, _producer)
            features = payload.get("features", [])
            if not features:
                continue
            geoms = [shape(f["geometry"]) for f in features]
            props = [f.get("properties", {}) for f in features]
            gdf = gpd.GeoDataFrame(props, geometry=geoms, crs="EPSG:4326")
            gdf["dataset"] = dataset
            frames.append(gdf)
            sources.append(
                Source(
                    name=f"planning.data.gov.uk: {dataset}",
                    url=meta.get("url", API_URL),
                    licence=self.licence,
                    licence_url="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                    note=f"{len(features)} feature(s) intersecting the AOI bbox",
                    commercial_ok=True,
                )
            )

        if not frames:
            return LayerResult(
                layer=self.layer,
                provider=self.name,
                gdf=None,
                sources=[],
                coverage=0.0,
                degraded=True,
                notes=["No planning.data.gov.uk constraint features intersect this AOI."],
            )

        combined = gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326"
        )
        combined = aoi.to_metric(combined)
        clipped = aoi.clip(combined)

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            gdf=clipped,
            sources=sources,
            coverage=1.0,
            degraded=False,
            notes=[
                "GB availability is a bounding-box test, not a coastline test; see "
                "UkConstraintsProvider.available.",
                f"Datasets queried: {', '.join(DATASETS)}.",
            ],
        )


REGISTRY.register(UkConstraintsProvider())
