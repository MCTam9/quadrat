"""Building use: tag first, then own tags, ground-floor POIs, then land-use zone."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point, box

from sce.aoi import AOI
from sce.building_use import infer_building_use, use_from_building_tag


def _aoi() -> AOI:
    return AOI.from_point(-0.1, 51.5, 500.0)


def test_tag_wins_and_yes_is_unknown():
    assert use_from_building_tag("apartments") == "residential"
    assert use_from_building_tag("yes") is None
    assert use_from_building_tag("bunker") == "other"


def test_inference_order_and_sources():
    aoi = _aoi()
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    boxes = [box(cx + i * 50, cy, cx + i * 50 + 20, cy + 20) for i in range(5)]
    b = gpd.GeoDataFrame(
        {
            "building": ["office", "yes", "yes", "yes", "yes"],
            "shop": [None, "bakery", None, None, None],
        },
        geometry=boxes,
        crs=aoi.crs,
    )
    # Building 2 holds two cafés and one shop -> retail by POI vote.
    pois = gpd.GeoDataFrame(
        {"category": ["food", "food", "civic"]},
        geometry=[Point(cx + 105, cy + 5), Point(cx + 110, cy + 10), Point(cx + 115, cy + 15)],
        crs=aoi.crs,
    )
    # Building 3 sits in a residential zone; building 4 in nothing.
    lu = gpd.GeoDataFrame(
        {"class": ["residential"]}, geometry=[box(cx + 140, cy - 10, cx + 180, cy + 30)], crs=aoi.crs
    )
    out = infer_building_use(b, pois, lu)
    assert list(out["use"][:4]) == ["commercial", "retail", "retail", "residential"]
    assert list(out["use_source"][:4]) == ["tag", "tags", "poi", "landuse"]
    assert out["use"].isna().iloc[4] and out["use_source"].isna().iloc[4]


def test_works_without_context_layers():
    aoi = _aoi()
    b = gpd.GeoDataFrame({"building": ["yes"]}, geometry=[aoi.geometry.buffer(-400)], crs=aoi.crs)
    out = infer_building_use(b)
    assert out["use"].isna().all()
