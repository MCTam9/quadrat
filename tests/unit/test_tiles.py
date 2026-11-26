"""OpenFreeMap tile providers, offline: synthetic tiles built with `mapbox_vector_tile.encode`."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest
from _tile_fixtures import MID_LAT, SEAM_LON, TX, TY, FakeNetwork, aoi
from pyproj import Transformer

from sce.cache import Cache
from sce.providers import openfreemap_tiles as t
from sce.registry import REGISTRY
from sce.types import LayerResult
from sce.vocab import LANDUSE_IDS, omt_landuse_class

# metres per tile pixel on the ground at the fixture's latitude
M_PER_PX = (40075016.68 / 2**t.ZOOM / t.EXTENT) * math.cos(math.radians(MID_LAT))


@pytest.fixture
def net(monkeypatch):
    return FakeNetwork().install(monkeypatch)


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "c", offline=False)


@pytest.fixture
def results(net, cache):
    return t.tile_results(aoi(), cache)


# -- tile arithmetic ---------------------------------------------------------------------------


def test_tile_bounds_match_the_slippy_map_scheme():
    w, s, e, n = t.tile_bounds_lonlat(0, 0, 0)
    assert (w, e) == (-180.0, 180.0)
    assert n == pytest.approx(85.0511287798) and s == pytest.approx(-85.0511287798)
    w, s, e, n = t.tile_bounds_lonlat(1, 1, 1)
    assert (w, e) == (0.0, 180.0) and n == pytest.approx(0.0, abs=1e-9)
    assert t.lonlat_to_tile(0.0001, -0.0001, 1) == (1, 1)
    assert t.lonlat_to_tile(-179.9, 85.0, 1) == (0, 0)


def test_the_tile_for_a_point_contains_it():
    x, y = t.lonlat_to_tile(-2.2453, 53.4794)
    w, s, e, n = t.tile_bounds_lonlat(x, y)
    assert w <= -2.2453 <= e and s <= 53.4794 <= n
    # z14 at 53 N is about 1.4-1.5 km wide, as the real service measures it
    width_m = (e - w) * 111_320 * math.cos(math.radians(53.4794))
    assert 1400 < width_m < 1500


def test_tile_grid_to_mercator_to_lonlat_agrees_with_tile_bounds():
    to_lonlat = Transformer.from_crs(3857, 4326, always_xy=True)
    for x, y in [(TX, TY), (8000, 5000)]:
        w, s, e, n = t.tile_bounds_lonlat(x, y)
        corners = np.array([[x, y], [x + 1, y + 1], [x + 0.5, y + 0.5]], dtype=float)
        lon, lat = to_lonlat.transform(*t.grid_to_mercator(corners).T)
        assert (lon[0], lat[0]) == pytest.approx((w, n), abs=1e-9)  # NW: y is down
        assert (lon[1], lat[1]) == pytest.approx((e, s), abs=1e-9)  # SE
        assert lon[2] == pytest.approx((w + e) / 2, abs=1e-9)


def test_tiles_cover_the_aoi_bbox():
    assert sorted(t.tiles_for_bbox(*aoi().bbox_wgs84)) == [(TX, TY), (TX + 1, TY)]


# -- decode: position, explode, seams ------------------------------------------------------


def test_decoded_buildings_land_where_the_tile_says(results):
    """The 12 m part at pixel (3000..3100, 1000..1100) of the west tile, y down."""
    b = results["buildings"].gdf
    cen = b.geometry.centroid.to_crs(4326)  # centroid in metres, then to degrees
    w, s, e, n = t.tile_bounds_lonlat(TX, TY)
    expect_lon = w + (e - w) * 3050 / 4096
    hit = cen[(abs(cen.x - expect_lon) < 1e-5) & (b.height_m == 12.0)]
    assert len(hit) == 1
    assert hit.x.iloc[0] == pytest.approx(expect_lon, abs=2e-6)
    # Web Mercator is linear in y, and pixel y runs DOWN from the north edge
    merc = lambda lat: math.asinh(math.tan(math.radians(lat)))  # noqa: E731
    frac = (merc(n) - merc(hit.y.iloc[0])) / (merc(n) - merc(s))
    assert frac == pytest.approx(1050 / 4096, abs=1e-4)


def test_multipolygon_parts_are_exploded(results):
    b = results["buildings"].gdf
    assert set(b.geom_type) == {"Polygon"}
    # the far 12 m part, the seam-straddling 12 m building, the 5 m one, the 0 m one: roof part dropped
    assert len(b) == 4
    assert sorted(b.height_m.dropna()) == [5.0, 12.0, 12.0]


def test_parts_split_by_a_tile_seam_are_dissolved_into_one(results):
    b = results["buildings"].gdf
    to_aoi = Transformer.from_crs(4326, b.crs, always_xy=True)
    sx, _ = to_aoi.transform(SEAM_LON, MID_LAT)
    straddling = b[(b.bounds.minx < sx - 1) & (b.bounds.maxx > sx + 1)]
    # two buildings cross the seam (12 m and 5 m), each as ONE polygon, not two halves
    assert sorted(straddling.height_m) == [5.0, 12.0]
    twelve = straddling[straddling.height_m == 12.0].iloc[0]
    # 96 px from the west tile plus 96 px from the east one, 100 px tall. (Area, not bounds: a
    # true-north square is slightly rotated in UTM, which inflates its bounding box.)
    assert twelve.geometry.area == pytest.approx(192 * 100 * M_PER_PX**2, rel=0.02)


def test_equal_attribute_buildings_away_from_a_seam_stay_separate(results):
    b = results["buildings"].gdf
    twelve = b[b.height_m == 12.0]
    assert len(twelve) == 2  # the one on the seam and the far part


def test_height_is_render_height_when_positive_else_nan(results):
    b = results["buildings"].gdf
    assert set(b.height_source[b.height_m.notna()]) == {"tiles"}
    assert b.height_m.isna().sum() == 1
    assert set(b.height_source[b.height_m.isna()]) == {""}
    assert b.height_m.dropna().gt(0).all()


def test_roads_cross_the_seam_as_one_line_and_map_to_web_classes(results):
    s = results["streets"].gdf
    assert set(s.geom_type) == {"LineString"}
    assert sorted(s.highway) == ["footway", "primary", "residential"]  # rail dropped, minor -> residential
    primary = s[s.highway == "primary"].iloc[0].geometry
    assert primary.length == pytest.approx((1096 + 1000) * M_PER_PX, rel=0.02)  # 3000..4096 plus 0..1000


def test_every_emitted_highway_is_styled_by_the_web():
    """STREET_CLASSES in web/lib/layers.ts is what colours streets: our classes must be listed there."""
    text = (Path(__file__).resolve().parents[2] / "web/lib/layers.ts").read_text()
    block = text[text.index("export const STREET_CLASSES") : text.index("export function streetClass")]
    known = set(re.findall(r'"([a-z_]+)"', " ".join(re.findall(r"match: \[(.*?)\]", block))))
    emitted = set(t._ROAD_CLASS.values()) | set(t._PATH_SUBCLASS.values()) | {"path"}
    assert emitted <= known, emitted - known


def test_landuse_polygons_use_the_vocabulary(results):
    lu = results["landuse"].gdf
    assert set(lu["class"]) <= set(LANDUSE_IDS)
    assert set(lu["class"]) == {"residential", "green_space", "water"}  # "neighbourhood" is not land use
    assert set(lu.omt_layer) == {"landuse", "landcover", "park", "water"}


def test_amenities_are_points_with_a_category_and_buffer_points_count_once(results):
    a = results["amenities"].gdf
    assert set(a.geom_type) == {"Point"}
    assert sorted(a.category) == ["food", "health"]  # bollard dropped; pharmacy counted once, not twice
    assert results["amenities"].coverage == pytest.approx(2 / 8)


def test_geometry_is_in_the_aoi_crs_and_inside_it(results):
    a = aoi()
    for r in results.values():
        assert r.gdf.crs == a.crs
        assert r.gdf.geometry.within(a.geometry.buffer(1.0)).all()


# -- mapping tables ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("layer", "value", "expected"),
    [
        ("landuse", "residential", "residential"),
        ("landuse", "railway", "transport"),
        ("landuse", "school", "civic"),
        ("landuse", "pitch", "green_space"),
        ("landuse", "neighbourhood", None),
        ("landcover", "grass", "green_space"),
        ("landcover", "farmland", "agriculture"),
        ("park", "national_park", "green_space"),
        ("park", "historic", None),
        ("water", "river", "water"),
        ("landuse", "no-such-thing", None),
    ],
)
def test_omt_landuse_mapping(layer, value, expected):
    assert omt_landuse_class(layer, value) == expected


def test_every_mapped_landuse_class_is_in_the_vocabulary():
    from sce.vocab import OMT_LANDUSE

    for mapping in OMT_LANDUSE.values():
        assert set(mapping.values()) <= set(LANDUSE_IDS)


@pytest.mark.parametrize(
    ("cls", "sub", "expected"),
    [
        ("restaurant", None, "food"),
        ("clothing_store", "clothes", "retail"),
        ("pharmacy", None, "health"),
        ("bus", "bus_stop", "transport"),
        ("post", "post_office", "civic"),
        ("post", "post_box", None),
        ("bollard", None, None),
        ("garden", "garden", None),
    ],
)
def test_poi_categories(cls, sub, expected):
    assert t.poi_category(cls, sub) == expected


@pytest.mark.parametrize(
    ("cls", "sub", "expected"),
    [
        ("minor", None, "residential"),
        ("path", "cycleway", "cycleway"),
        ("path", None, "path"),
        ("rail", None, None),
    ],
)
def test_road_classes(cls, sub, expected):
    assert t.road_highway(cls, sub) == expected


# -- provenance: degraded, notes, attribution ----------------------------------------------


def test_every_tile_result_is_degraded_with_a_note_and_credit(results):
    assert set(results) == {"buildings", "streets", "landuse", "amenities"}
    for layer, r in results.items():
        assert r.provider == f"tiles_{layer}" and r.degraded
        assert r.notes[0].startswith("From map tiles:")
        names = " ".join(s.name for s in r.sources)
        assert "OpenMapTiles" in names and "OpenStreetMap contributors" in names
    assert results["buildings"].notes[0] == "From map tiles: building counts and types approximate"


def test_degraded_survives_a_clip_to_a_smaller_square(results):
    from sce.clip import clip_layers

    outer, inner = aoi(500.0), aoi(100.0)
    inner = type(inner).from_point(SEAM_LON, MID_LAT, 100.0, name="in", crs=outer.crs)
    clipped = clip_layers(results, outer, inner)
    assert clipped
    assert all(r.degraded and r.notes[0].startswith("From map tiles:") for r in clipped.values())


def test_attribution_and_export_readme_name_openmaptiles(results, tmp_path):
    import sce.providers  # noqa: F401
    from sce.export.attribution import generate_attribution
    from sce.export.bundle import readme_text

    text = generate_attribution(REGISTRY, tmp_path / "A.md").read_text()
    for name in ("tiles_buildings", "tiles_streets", "tiles_landuse", "tiles_amenities"):
        assert name in text
    assert "OpenMapTiles" in text and "OpenStreetMap contributors" in text
    committed = (Path(__file__).resolve().parents[2] / "ATTRIBUTION.md").read_text()
    assert committed == text, "ATTRIBUTION.md is stale: run `sce attribution`"
    readme = readme_text(aoi(), results, ["README.txt"])
    assert "OpenMapTiles" in readme and "OpenStreetMap contributors" in readme
    assert "ODbL" in readme  # share-alike applies to tile-derived layers too


# -- the registry chain and one fetch per load ------------------------------------------------


def test_tile_providers_rank_after_every_osm_provider():
    import sce.providers  # noqa: F401

    for layer in ("buildings", "streets", "landuse", "amenities"):
        chain = [p.name for p in REGISTRY.providers(layer)]
        assert chain[-1] == f"tiles_{layer}"
        assert chain[0].startswith("osm_")


def test_four_providers_share_one_fetch_and_decode(net, cache):
    a = aoi()
    for layer in ("buildings", "streets", "landuse", "amenities"):
        assert REGISTRY.provider(f"tiles_{layer}").fetch(a, cache).layer == layer
    assert sorted(net.tile_calls) == [(TX, TY), (TX + 1, TY)]
    assert net.tilejson_calls == 1


def test_tilejson_is_read_once_and_the_version_is_in_the_cache_key(net, cache):
    t.tile_results(aoi(500.0), cache)
    t.tile_results(aoi(450.0), cache)  # a different AOI: new decode, but tiles come from the disk cache
    assert net.tilejson_calls == 1
    assert sorted(net.tile_calls) == [(TX, TY), (TX + 1, TY)]
    key = cache.key("ofm", "20260101_000000_pt", t.ZOOM, TX, TY)
    assert cache.has(key, ".pbf")


def test_registry_notes_do_not_leak_into_the_shared_result(net, cache):
    a = aoi()
    p = REGISTRY.provider("tiles_buildings")
    first = p.fetch(a, cache)
    first.notes.append("scribble")
    first.gdf["height_m"] = -1
    again = p.fetch(a, cache)
    assert "scribble" not in again.notes
    assert (again.gdf["height_m"].dropna() > 0).all()


def test_a_missing_tile_is_empty_not_fatal(monkeypatch, cache):
    net = FakeNetwork({(TX, TY): FakeNetwork().tiles[(TX, TY)]}).install(monkeypatch)
    res = t.tile_results(aoi(), cache)  # the east tile is a 404 -> empty bytes
    assert res["buildings"].gdf is not None
    assert net.tile_calls.count((TX + 1, TY)) == 1


def test_all_tiles_failing_raises_and_is_not_remembered(monkeypatch, cache):
    FakeNetwork().install(monkeypatch)

    def boom(url):
        raise OSError("down")

    monkeypatch.setattr(t, "_get_tile", boom)
    with pytest.raises(RuntimeError):
        t.tile_results(aoi(), cache)
    FakeNetwork().install(monkeypatch)
    assert t.tile_results(aoi(), cache)


def test_offline_cache_never_touches_the_network(monkeypatch):
    FakeNetwork().install(monkeypatch)
    with pytest.raises(FileNotFoundError):
        t.tile_results(aoi(), Cache(offline=True))


# -- no street graph ------------------------------------------------------------------------


def test_street_and_access_metrics_degrade_without_a_graph(results):
    from sce.metrics import compute_all
    from sce.metrics.access import access_metrics
    from sce.metrics.street import street_metrics

    a = aoi()
    layers = {"streets": results["streets"], "amenities": results["amenities"]}
    assert layers["streets"].data is None
    sm = street_metrics(layers, a)
    assert sm["intersection_count"] is None and sm["dead_end_share"] is None
    assert sm["orientation_order_phi"] is None and sm["graph_available"] is False
    assert sm["street_length_km"] > 0
    am = access_metrics(layers, a)
    assert am["walk_reach_ratio_10min"] is None
    assert am["amenity_category_count_10min"] == 2
    out = compute_all(results, a)
    assert out["errors"] == {}
    assert out["street"]["street_length_km"] > 0


# -- snapshots ------------------------------------------------------------------------------


def test_tile_layers_survive_snapshot_and_restore(results):
    from sce.site import Site

    site = Site(aoi(), dict(results))
    back = Site.restore(site.snapshot())
    assert set(back.layers) == set(results)
    for name, r in back.layers.items():
        assert isinstance(r, LayerResult) and r.provider == f"tiles_{name}"
        assert r.degraded and r.notes[0].startswith("From map tiles:")
        assert len(r.gdf) == len(results[name].gdf)
    # and the restored site can still be viewed
    sq = back.square(SEAM_LON, MID_LAT, 400.0)
    assert back.preview(sq)["buildings"]["features"]
