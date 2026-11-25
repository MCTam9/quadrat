"""Building use: from the `building` tag where OSM has one, inferred where it does not.

Most OSM buildings in dense centres are tagged only `building=yes` (two thirds
of a central-London square), so colouring by the tag alone leaves the map grey.
Three weaker sources of evidence are already in the fetched layers, tried in
order of how directly they describe the building:

1. `tags`: the footprint's own amenity/shop/office/tourism/healthcare tags.
2. `poi`: shops, cafés, offices and civic amenities mapped as points inside the
   footprint, by majority. This is usually the GROUND-FLOOR use; upper floors
   of a London shop are often flats or offices, so it is labelled as such.
3. `landuse`: the OSM land-use zone containing the footprint.

Every building records which source answered (`use_source`), so the map and
the legend can say how much of the colouring is tagged and how much inferred.
A building no source can describe stays `unknown`; nothing is guessed beyond
the evidence.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

USES = ("residential", "commercial", "retail", "industrial", "civic", "other")

_BUILDING_TAG: dict[str, str] = {}
for _use, _tags in {
    "residential": "residential house detached semidetached_house terrace terraced_house apartments flats "
    "bungalow dormitory houseboat static_caravan cabin farm",
    "commercial": "commercial office offices hotel bank",
    "retail": "retail supermarket kiosk shop mall",
    "industrial": "industrial warehouse factory manufacture service storage_tank",
    "civic": "civic public government school university college kindergarten hospital church chapel "
    "cathedral mosque synagogue temple religious monastery fire_station train_station transportation "
    "museum library theatre sports_hall",
}.items():
    for _t in _tags.split():
        _BUILDING_TAG[_t] = _use

# Categories assigned by sce/providers/osm_amenities.py -> building use.
_POI_CATEGORY = {
    "food": "retail",
    "retail": "retail",
    "civic": "civic",
    "health": "civic",
    "education": "civic",
    "leisure": "other",
}

# Classes assigned by sce/providers/osm_landuse.py -> building use.
_LANDUSE_CLASS = {
    "residential": "residential",
    "commercial": "commercial",
    "retail": "retail",
    "industrial": "industrial",
    "institutional": "civic",
}

_CIVIC_AMENITIES = {
    "school",
    "university",
    "college",
    "kindergarten",
    "hospital",
    "clinic",
    "library",
    "townhall",
    "courthouse",
    "police",
    "fire_station",
    "place_of_worship",
    "community_centre",
    "embassy",
    "theatre",
    "arts_centre",
    "museum",
}


def _text(v: Any) -> str | None:
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().lower()
    return s or None


def use_from_building_tag(tag: Any) -> str | None:
    """Use implied by the OSM `building` value, or None for `yes`/unknown values."""
    t = _text(tag)
    if t is None or t == "yes":
        return None
    return _BUILDING_TAG.get(t, "other")


def use_from_own_tags(row: dict[str, Any]) -> str | None:
    """Use implied by the footprint's own non-building tags."""
    amenity = _text(row.get("amenity"))
    if amenity in _CIVIC_AMENITIES or _text(row.get("healthcare")) or _text(row.get("religion")):
        return "civic"
    if _text(row.get("office")):
        return "commercial"
    if _text(row.get("tourism")) in {"hotel", "hostel", "guest_house", "apartment"}:
        return "commercial"
    if _text(row.get("shop")) or amenity in {"restaurant", "cafe", "pub", "bar", "fast_food", "bank"}:
        return "retail"
    if amenity:
        return "other"
    return None


def infer_building_use(buildings: Any, amenities: Any = None, landuse: Any = None) -> pd.DataFrame:
    """`use` and `use_source` for every building, aligned to `buildings.index`.

    All three frames must share one metric CRS (the AOI's); `amenities` and
    `landuse` may be None.
    """
    import geopandas as gpd

    n = len(buildings)
    use: list[str | None] = [None] * n
    source: list[str | None] = [None] * n
    records = buildings.drop(columns=buildings.geometry.name).to_dict("records")
    for i, row in enumerate(records):
        u = use_from_building_tag(row.get("building"))
        if u is not None:
            use[i], source[i] = u, "tag"
            continue
        u = use_from_own_tags(row)
        if u is not None:
            use[i], source[i] = u, "tags"

    pending = [i for i in range(n) if use[i] is None]
    positions = pd.Series(range(n), index=buildings.index)

    if pending and amenities is not None and len(amenities) and "category" in amenities.columns:
        pts = amenities[amenities.geometry.geom_type == "Point"][["category", "geometry"]]
        target = buildings.iloc[pending][[buildings.geometry.name]]
        if len(pts) and len(target):
            hits = gpd.sjoin(pts, target, predicate="within", how="inner")
            votes: dict[int, Counter] = {}
            for idx, cat in zip(hits["index_right"], hits["category"], strict=True):
                mapped = _POI_CATEGORY.get(cat)
                if mapped:
                    votes.setdefault(int(positions[idx]), Counter())[mapped] += 1
            for pos, counter in votes.items():
                use[pos], source[pos] = counter.most_common(1)[0][0], "poi"

    pending = [i for i in range(n) if use[i] is None]
    if pending and landuse is not None and len(landuse) and "class" in landuse.columns:
        zones = landuse[landuse["class"].isin(_LANDUSE_CLASS)][["class", "geometry"]]
        if len(zones):
            cent = gpd.GeoDataFrame(
                geometry=buildings.iloc[pending].geometry.representative_point(), crs=buildings.crs
            )
            hits = gpd.sjoin(cent, zones, predicate="within", how="inner")
            for idx, cls in zip(hits.index, hits["class"], strict=True):
                pos = int(positions[idx])
                if use[pos] is None:
                    use[pos], source[pos] = _LANDUSE_CLASS[cls], "landuse"

    return pd.DataFrame({"use": use, "use_source": source}, index=buildings.index)
