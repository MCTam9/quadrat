"""Unit tests for sce/aoi.py: the CRS spine.

sce/aoi.py is a "do not modify" spine file (see CONTRIBUTING.md); these tests
exercise its documented public surface without assuming anything about its
internals beyond what CONTRIBUTING.md promises.
"""

from __future__ import annotations

import pytest
from pyproj import CRS
from shapely.geometry import Point, Polygon, mapping

from sce.aoi import AOI, NonMetricCRSError

# ---------------------------------------------------------------------------
# from_point
# ---------------------------------------------------------------------------


def test_from_point_basic_shape_and_crs():
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")
    assert aoi.name == "tashkent"
    assert isinstance(aoi.geometry, Polygon)
    assert not CRS.from_user_input(aoi.crs).is_geographic
    assert aoi.centroid_lonlat == (69.2401, 41.2995)
    assert aoi.radius_m == 1500


def test_from_point_geometry_is_a_square_of_the_right_size():
    aoi = AOI.from_point(0.0, 0.0, 500.0, name="square")
    minx, miny, maxx, maxy = aoi.geometry.bounds
    assert maxx - minx == pytest.approx(1000.0, rel=1e-9)
    assert maxy - miny == pytest.approx(1000.0, rel=1e-9)
    assert aoi.area_m2 == pytest.approx(1_000_000.0, rel=1e-9)
    assert aoi.area_ha == pytest.approx(100.0, rel=1e-9)
    assert aoi.area_km2 == pytest.approx(1.0, rel=1e-9)


@pytest.mark.parametrize(
    "lon,lat",
    [(-180.1, 0.0), (180.1, 0.0), (0.0, -90.1), (0.0, 90.1), (200.0, 200.0)],
)
def test_from_point_rejects_out_of_range_lon_lat(lon, lat):
    with pytest.raises(ValueError):
        AOI.from_point(lon, lat, 1000.0, name="bad")


@pytest.mark.parametrize("radius_m", [0.0, -1.0, -1000.0])
def test_from_point_rejects_non_positive_radius(radius_m):
    with pytest.raises(ValueError):
        AOI.from_point(0.0, 0.0, radius_m, name="bad-radius")


def test_from_point_accepts_boundary_lon_lat():
    # Exactly on the documented inclusive boundary should not raise.
    AOI.from_point(-180.0, -90.0, 1000.0, name="corner-sw")
    AOI.from_point(180.0, 90.0, 1000.0, name="corner-ne")


# ---------------------------------------------------------------------------
# from_geojson
# ---------------------------------------------------------------------------


def _square_geojson(cx: float, cy: float, half: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [cx - half, cy - half],
                [cx + half, cy - half],
                [cx + half, cy + half],
                [cx - half, cy + half],
                [cx - half, cy - half],
            ]
        ],
    }


def test_from_geojson_bare_geometry():
    geom = _square_geojson(69.24, 41.30, 0.01)
    aoi = AOI.from_geojson(geom, name="from-geom")
    assert not CRS.from_user_input(aoi.crs).is_geographic
    assert aoi.area_m2 > 0
    assert aoi.radius_m is None
    assert aoi.meta["kind"] == "geojson"


def test_from_geojson_feature():
    geom = _square_geojson(-0.13, 51.51, 0.01)
    feature = {"type": "Feature", "properties": {}, "geometry": geom}
    aoi = AOI.from_geojson(feature, name="from-feature")
    assert not CRS.from_user_input(aoi.crs).is_geographic
    assert aoi.area_m2 > 0


def test_from_geojson_feature_collection_single_feature():
    geom = _square_geojson(46.68, 24.71, 0.01)
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geom}]}
    aoi = AOI.from_geojson(fc, name="from-fc")
    assert not CRS.from_user_input(aoi.crs).is_geographic


def test_from_geojson_feature_collection_multiple_features_unions():
    geom_a = _square_geojson(69.24, 41.30, 0.005)
    geom_b = _square_geojson(69.26, 41.32, 0.005)
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": geom_a},
            {"type": "Feature", "properties": {}, "geometry": geom_b},
        ],
    }
    aoi = AOI.from_geojson(fc, name="from-fc-multi")
    assert not CRS.from_user_input(aoi.crs).is_geographic
    assert aoi.area_m2 > 0


def test_from_geojson_empty_geometry_raises():
    from shapely.errors import GEOSException

    empty = mapping(Polygon())
    # An empty geometry has no centroid to build a CRS around; from_geojson
    # fails while computing it (GEOSException) before AOI.__post_init__'s own
    # "empty geometry" ValueError ever gets a chance to fire.
    with pytest.raises((ValueError, GEOSException)):
        AOI.from_geojson(empty, name="empty")


# ---------------------------------------------------------------------------
# clip / to_metric
# ---------------------------------------------------------------------------


def test_to_metric_reprojects_and_none_or_empty_passthrough():
    gpd = pytest.importorskip("geopandas")
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")

    assert aoi.to_metric(None) is None
    empty = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    assert len(aoi.to_metric(empty)) == 0

    gdf = gpd.GeoDataFrame({"geometry": [Point(69.2401, 41.2995)]}, crs="EPSG:4326")
    out = aoi.to_metric(gdf)
    assert CRS.from_user_input(out.crs) == aoi.crs


def test_to_metric_requires_a_crs():
    gpd = pytest.importorskip("geopandas")
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")
    gdf = gpd.GeoDataFrame({"geometry": [Point(0, 0)]})  # no crs set
    with pytest.raises(NonMetricCRSError):
        aoi.to_metric(gdf)


def test_clip_rejects_geographic_crs():
    gpd = pytest.importorskip("geopandas")
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")
    gdf = gpd.GeoDataFrame({"geometry": [Point(69.2401, 41.2995)]}, crs="EPSG:4326")
    with pytest.raises(NonMetricCRSError):
        aoi.clip(gdf)


def test_clip_reprojects_a_different_metric_crs_then_clips():
    gpd = pytest.importorskip("geopandas")
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")
    other_metric_crs = "EPSG:3857"
    pt_wgs84 = gpd.GeoDataFrame({"geometry": [Point(*aoi.centroid_lonlat)]}, crs="EPSG:4326")
    pt_other = pt_wgs84.to_crs(other_metric_crs)
    clipped = aoi.clip(pt_other)
    assert CRS.from_user_input(clipped.crs) == aoi.crs
    assert len(clipped) == 1


def test_clip_none_or_empty_passthrough():
    gpd = pytest.importorskip("geopandas")
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")
    assert aoi.clip(None) is None
    empty = gpd.GeoDataFrame({"geometry": []}, crs=aoi.crs)
    assert len(aoi.clip(empty)) == 0


# ---------------------------------------------------------------------------
# bbox_wgs84 round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lon,lat",
    [(69.2401, 41.2995), (-0.1276, 51.5072), (46.6753, 24.7136), (0.0, 0.0), (179.0, -60.0)],
)
def test_bbox_wgs84_round_trips_the_centre(lon, lat):
    from pyproj import Transformer

    aoi = AOI.from_point(lon, lat, 800.0, name="roundtrip")
    w, s, e, n = aoi.bbox_wgs84
    assert w < lon < e
    assert s < lat < n

    # Round-trip the requested centre itself: project it into the AOI's
    # metric CRS (out) and back to WGS84 (back), and require sub-micro-degree
    # agreement. A square's bbox midpoint in degrees is a separate, looser
    # question (projection distortion skews it off-centre by more than
    # 1e-6 deg) so it is checked only loosely, not to this tolerance.
    to_metric = Transformer.from_crs("EPSG:4326", aoi.crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(aoi.crs, "EPSG:4326", always_xy=True)
    mx, my = to_metric.transform(lon, lat)
    back_lon, back_lat = to_wgs84.transform(mx, my)
    assert back_lon == pytest.approx(lon, abs=1e-6)
    assert back_lat == pytest.approx(lat, abs=1e-6)

    mid_lon = (w + e) / 2
    mid_lat = (s + n) / 2
    assert mid_lon == pytest.approx(lon, abs=1e-2)
    assert mid_lat == pytest.approx(lat, abs=1e-2)


def test_geometry_wgs84_matches_bbox_wgs84():
    aoi = AOI.from_point(69.2401, 41.2995, 800.0, name="wgs84-consistency")
    assert tuple(round(v, 9) for v in aoi.geometry_wgs84.bounds) == tuple(round(v, 9) for v in aoi.bbox_wgs84)


# ---------------------------------------------------------------------------
# key() stability
# ---------------------------------------------------------------------------


def test_key_is_stable_and_deterministic():
    a = AOI.from_point(69.2401, 41.2995, 1500, name="k1")
    b = AOI.from_point(69.2401, 41.2995, 1500, name="k2")
    assert a.key() == b.key()  # name is not part of identity


def test_key_differs_by_location_or_radius():
    base = AOI.from_point(69.2401, 41.2995, 1500, name="base")
    moved = AOI.from_point(69.2500, 41.2995, 1500, name="moved")
    bigger = AOI.from_point(69.2401, 41.2995, 2000, name="bigger")
    assert base.key() != moved.key()
    assert base.key() != bigger.key()


def test_key_contains_epsg():
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="k")
    assert aoi.epsg in aoi.key()


# ---------------------------------------------------------------------------
# provenance()
# ---------------------------------------------------------------------------


def test_provenance_shape():
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="prov")
    prov = aoi.provenance()
    assert prov["name"] == "prov"
    assert prov["lon"] == pytest.approx(69.2401)
    assert prov["lat"] == pytest.approx(41.2995)
    assert prov["radius_m"] == 1500
    assert prov["crs"] == aoi.epsg
    assert isinstance(prov["crs_wkt_name"], str)
    assert prov["area_ha"] == pytest.approx(aoi.area_ha, abs=0.01)
    assert prov["area_km2"] == pytest.approx(aoi.area_km2, abs=1e-4)
    assert len(prov["bbox_wgs84"]) == 4
    assert prov["kind"] == "point-square"
    assert prov["requested_radius_m"] == 1500


def test_provenance_is_json_serialisable():
    import json

    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="prov-json")
    json.dumps(aoi.provenance())


# ---------------------------------------------------------------------------
# epsg property
# ---------------------------------------------------------------------------


def test_epsg_property_format():
    aoi = AOI.from_point(69.2401, 41.2995, 1500, name="epsg")
    assert aoi.epsg.startswith("EPSG:")
    assert aoi.epsg[5:].isdigit()


def test_epsg_property_falls_back_to_crs_string_for_laea():
    aoi = AOI.from_point(0.0, 85.0, 1500, name="laea-epsg")
    # LAEA CRSes built from a custom proj4 string have no EPSG code.
    assert aoi.crs.to_epsg() is None
    assert aoi.epsg == aoi.crs.to_string()
