"""Faster site loads: timings, one shared Overpass query, lazy climate, LiDAR focus, locks. Offline."""

from __future__ import annotations

import logging
import threading
import time

import geopandas as gpd
import osmnx as ox
import pandas as pd
import pytest
from _site_fixtures import LAT, LON, site_layers
from shapely.geometry import Point, box

from sce import pipeline
from sce.aoi import AOI
from sce.cache import Cache
from sce.providers import _overpass
from sce.site import CONTEXT_RING_M, Site
from sce.types import LayerResult

# -- fetch_layers timings, groups and LiDAR focus --------------------------------


@pytest.fixture
def fake_registry(monkeypatch):
    """Registry whose providers answer instantly; records which AOI each layer was fetched for."""
    from sce.registry import REGISTRY

    seen: dict[str, AOI] = {}
    order: list[str] = []

    def fetch(layer, aoi, cache, **kw):
        seen[layer] = aoi
        order.append(layer)
        time.sleep(0.01)
        return LayerResult(layer, "fake", data={"x": 1})

    monkeypatch.setattr(REGISTRY, "fetch", fetch)
    monkeypatch.setattr(REGISTRY, "chain", lambda layer, aoi: [object()])
    return seen, order


def test_fetch_layers_records_ms_per_layer(fake_registry):
    aoi = AOI.from_point(LON, LAT, 500, name="t")
    timings: dict[str, int] = {}
    seen: list[str] = []
    out = pipeline.fetch_layers(aoi, object(), on_layer=lambda n, r: seen.append(n), timings=timings)
    assert set(timings) == set(pipeline.LAYERS) | {"heights"}
    assert all(isinstance(v, int) and v >= 10 for k, v in timings.items() if k != "heights")
    assert set(out) == set(pipeline.LAYERS) and set(seen) == set(pipeline.LAYERS)


def test_feature_layers_share_one_worker_and_streets_another(fake_registry):
    _, order = fake_registry
    aoi = AOI.from_point(LON, LAT, 500, name="t")
    pipeline.fetch_layers(aoi, object())
    feats = [layer for layer in order if layer in pipeline.OSM_FEATURE_LAYERS]
    assert feats == list(pipeline.OSM_FEATURE_LAYERS)  # one worker, in order
    assert pipeline.OSM_GROUPS[0] == ("streets",)


def test_building_height_fetched_for_the_focus_only(fake_registry):
    seen, _ = fake_registry
    aoi = AOI.from_point(LON, LAT, 600, name="t")
    focus = AOI.from_point(LON, LAT, 300, name="focus", crs=aoi.crs)
    pipeline.fetch_layers(aoi, object(), only=["buildings", "building_height"], height_focus=focus)
    assert seen["building_height"].radius_m == 300
    assert seen["buildings"].radius_m == 600


def test_site_load_asks_for_square_plus_ring_and_no_climate(monkeypatch):
    got = {}

    def fetch(aoi, cache, *, on_layer=None, only=None, timings=None, height_focus=None):
        got.update(aoi=aoi, only=only, focus=height_focus)
        return {k: v for k, v in site_layers(aoi).items() if k in only}

    Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch)
    assert "climate" not in got["only"] and "building_height" in got["only"]
    assert got["focus"].radius_m == 300.0 + CONTEXT_RING_M
    assert got["aoi"].radius_m == 600.0
    Site.load(LON, LAT, None, cache=object(), fetch=fetch)
    assert got["focus"] is None  # unknown square: LiDAR for the whole padded area


def test_load_logs_one_info_line_with_every_layer_ms(caplog):
    def fetch(aoi, cache, *, on_layer=None, only=None, timings=None, height_focus=None):
        layers = {k: v for k, v in site_layers(aoi).items() if k in only}
        for name, res in layers.items():
            timings[name] = 7
            on_layer(name, res)
        return layers

    seen = []
    with caplog.at_level(logging.INFO, logger="sce.site"):
        site = Site.load(
            LON, LAT, 300.0, cache=object(), fetch=fetch, on_layer=lambda n, r, ms: seen.append(ms)
        )
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("site load")]
    assert len(lines) == 1 and "buildings=7ms" in lines[0] and "total=" in lines[0]
    assert seen and set(seen) == {7}
    assert site.timings["total"] >= 0


def test_clip_drops_a_raster_that_misses_the_square():
    from dataclasses import replace

    from sce.clip import clip_layers

    outer = AOI.from_point(LON, LAT, 1000, name="outer")
    layers = site_layers(outer)
    focus = AOI.from_point(LON, LAT, 100, name="focus", crs=outer.crs)
    # a raster fetched for the focus only, queried for a square 600 m away
    import numpy as np
    from affine import Affine

    from sce.raster import SiteRaster

    fminx, fminy, fmaxx, fmaxy = focus.bounds_metric
    ras = SiteRaster.from_array(
        np.ones((20, 20), dtype=float), Affine(10, 0, fminx, 0, -10, fmaxy), outer.crs, square=focus
    )
    layers["terrain"] = replace(layers["terrain"], raster=ras)
    inner = AOI.from_point(LON, LAT, 100, name="inner", crs=outer.crs)
    shifted = AOI.from_point(LON + 0.009, LAT, 100, name="shifted", crs=outer.crs)
    assert "terrain" in clip_layers(layers, outer, inner)
    assert "terrain" not in clip_layers(layers, outer, shifted)


# -- lazy climate ------------------------------------------------------------------


def _site_without_climate(calls):
    def fetch(aoi, cache, *, on_layer=None, only=None, timings=None, height_focus=None):
        calls.append(only)
        return {k: v for k, v in site_layers(aoi).items() if only is None or k in only}

    return Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch), fetch


def test_climate_is_fetched_once_on_demand():
    calls: list = []
    site, _ = _site_without_climate(calls)
    assert "climate" not in site.layers and calls == [list(pipeline.SITE_LAYERS)]
    first = site.climate()
    assert len(first["typical_year"]["hourly"]["temperature_c"]) == 8760
    assert site.climate() is first
    assert calls[1:] == [["climate"]]


def test_analyse_includes_climate_metrics_and_survives_a_climate_failure():
    calls: list = []
    site, _ = _site_without_climate(calls)
    d = site.analyse(site.square(LON, LAT, 300.0))
    assert d["metrics"]["climate"]

    def boom(*a, **k):
        raise RuntimeError("open-meteo down")

    site2, _ = _site_without_climate([])
    site2._fetch_fn = boom
    d2 = site2.analyse(site2.square(LON, LAT, 300.0))
    assert "climate" not in d2["metrics"] and "fabric" in d2["metrics"]
    assert site2.climate_layer is not None
    with pytest.raises(RuntimeError):
        site2.climate()  # the failure is surfaced to /api/climate, and not remembered


# -- layers_for under concurrency --------------------------------------------------


def test_concurrent_views_clip_once(monkeypatch):
    import sce.site as mod

    site, _ = _site_without_climate([])
    clips = []
    real = mod.clip_layers

    def slow_clip(*a):
        clips.append(1)
        time.sleep(0.2)
        return real(*a)

    monkeypatch.setattr(mod, "clip_layers", slow_clip)
    sq = site.square(LON, LAT, 300.0)
    results = []
    threads = [threading.Thread(target=lambda: results.append(site.layers_for(sq))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(clips) == 1
    assert results[0] is results[1]


# -- one Overpass query for buildings, landuse and amenities ----------------------


def _osm_gdf(aoi):
    """What osmnx returns: a (element, id) index, tag columns, WGS84 geometry."""
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    geoms = [
        box(cx - 50, cy - 50, cx - 20, cy - 20),  # building
        box(cx + 20, cy + 20, cx + 60, cy + 60),  # building that is also a cafe
        box(cx - 200, cy + 20, cx - 100, cy + 120),  # park
        Point(cx + 80, cy - 80),  # shop node
        box(cx + 100, cy - 200, cx + 150, cy - 150),  # leisure=track: amenities only
        box(cx - 300, cy - 300, cx - 250, cy - 250),  # natural=cliff: nobody's
    ]
    gdf = gpd.GeoDataFrame(
        {
            "building": ["yes", "retail", None, None, None, None],
            "height": ["12", None, None, None, None, None],
            "amenity": [None, "cafe", None, None, None, None],
            "leisure": [None, None, "park", None, "track", None],
            "landuse": [None, None, None, None, None, None],
            "shop": [None, None, None, "bakery", None, None],
            "natural": [None, None, None, None, None, "cliff"],
        },
        geometry=geoms,
        crs=aoi.crs,
    ).to_crs(4326)
    gdf.index = pd.MultiIndex.from_tuples([("way", i) for i in range(len(gdf))], names=["element", "id"])
    return gdf


@pytest.fixture
def one_query(monkeypatch, tmp_path):
    _overpass._memo.clear()
    aoi = AOI.from_point(LON, LAT, 300, name="t")
    queries: list[dict] = []
    gdf = _osm_gdf(aoi)

    def fake(polygon, tags):
        queries.append(tags)
        return gdf.copy()

    monkeypatch.setattr(ox.features, "features_from_polygon", fake)
    monkeypatch.setattr(_overpass, "configure_osmnx", lambda cache: None)
    for mod in ("osm_buildings", "osm_landuse", "osm_amenities"):
        monkeypatch.setattr(f"sce.providers.{mod}.configure_osmnx", lambda cache: None)
    yield aoi, queries, Cache(root=tmp_path, offline=False)
    _overpass._memo.clear()


def test_one_overpass_call_serves_three_layers_with_the_right_split(one_query):
    import sce.providers  # noqa: F401
    from sce.registry import REGISTRY

    aoi, queries, cache = one_query
    b = REGISTRY.provider("osm_buildings").fetch(aoi, cache)
    lu = REGISTRY.provider("osm_landuse").fetch(aoi, cache)
    am = REGISTRY.provider("osm_amenities").fetch(aoi, cache)

    assert len(queries) == 1
    assert set(queries[0]) >= {"building", "landuse", "amenity", "shop", "natural", "leisure"}
    assert queries[0]["leisure"] is True and queries[0]["building"] is True

    assert len(b.gdf) == 2 and set(b.gdf["building"]) == {"yes", "retail"}
    assert sorted(b.gdf["height_m"].dropna()) == [12.0]
    assert list(lu.gdf["class"]) == ["green_space"]
    assert len(am.gdf) == 4  # cafe, park (leisure), bakery, track; polygons reduced to points
    assert set(am.gdf.geometry.geom_type) == {"Point"}
    assert set(am.gdf["category"]) >= {"food", "retail"}


def test_features_are_memoised_per_polygon(one_query):
    aoi, queries, _ = one_query
    from sce.providers.osm_buildings import TAGS

    _overpass.shared_features(aoi.geometry_wgs84, TAGS)
    _overpass.shared_features(aoi.geometry_wgs84, TAGS)
    other = AOI.from_point(LON + 0.01, LAT, 300, name="o")
    _overpass.shared_features(other.geometry_wgs84, TAGS)
    assert len(queries) == 2


def test_failures_are_not_memoised(monkeypatch):
    _overpass._memo.clear()
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api")
    _overpass._down_until.clear()
    calls = []

    def flaky(polygon, tags):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("502")
        return gpd.GeoDataFrame({"building": ["yes"]}, geometry=[Point(0, 0)], crs=4326)

    monkeypatch.setattr(ox.features, "features_from_polygon", flaky)
    poly = box(0, 0, 1, 1)
    with pytest.raises(RuntimeError):
        _overpass.shared_features(poly, {"building": True})
    _overpass._down_until.clear()
    assert len(_overpass.shared_features(poly, {"building": True})) == 1
    _overpass._memo.clear()


def test_union_tags_lets_true_absorb_lists():
    assert _overpass.union_tags({"leisure": ["park"]}, {"leisure": True}) == {"leisure": True}
    assert _overpass.union_tags({"natural": ["water"]}, {"natural": ["wood", "water"]}) == {
        "natural": ["water", "wood"]
    }


# -- osmnx settings are shared safely between threads -----------------------------


def test_same_endpoint_queries_overlap_but_never_see_another_endpoint(monkeypatch):
    monkeypatch.setenv("SCE_OVERPASS_URLS", "https://a.example/api")
    _overpass._down_until.clear()
    both_in = threading.Barrier(2, timeout=5)  # only passes if the two queries really overlap
    seen = []

    def query():
        both_in.wait()
        seen.append(ox.settings.overpass_url)
        return "ok"

    before = ox.settings.overpass_url
    with_threads = [
        threading.Thread(target=_overpass.with_overpass_fallback, args=(query,)) for _ in range(2)
    ]
    for t in with_threads:
        t.start()
    for t in with_threads:
        t.join()
    assert seen == ["https://a.example/api"] * 2
    assert ox.settings.overpass_url == before  # restored once the last query left


def test_different_endpoints_do_not_overlap():
    _overpass._down_until.clear()
    lock = threading.Lock()
    state = {"inside": 0, "max": 0, "wrong_url": 0}

    def run(url):
        _overpass._gate.enter(url)
        try:
            with lock:
                state["inside"] += 1
                state["max"] = max(state["max"], state["inside"])
                state["wrong_url"] += ox.settings.overpass_url != url
            time.sleep(0.05)
            with lock:
                state["inside"] -= 1
        finally:
            _overpass._gate.leave()

    urls = ("https://a.example/api", "https://b.example/api")
    threads = [threading.Thread(target=run, args=(u,)) for u in urls]
    threads[0].start()
    time.sleep(0.01)
    threads[1].start()
    for t in threads:
        t.join()
    assert state == {"inside": 0, "max": 1, "wrong_url": 0}


# -- planning constraints: four datasets in parallel -----------------------------


def test_constraint_datasets_are_fetched_in_parallel_and_in_order(monkeypatch, tmp_path):
    import requests

    from sce.providers import uk_constraints as mod

    aoi = AOI.from_point(-0.1276, 51.5072, 300, name="t")
    barrier = threading.Barrier(len(mod.DATASETS), timeout=5)  # passes only if all four run at once

    class Resp:
        def __init__(self, dataset):
            self.url = f"https://x/{dataset}"
            self._d = dataset

        def raise_for_status(self):
            pass

        def json(self):
            w, s, e, n = aoi.bbox_wgs84
            geom = box((w + e) / 2 - 0.0005, (s + n) / 2 - 0.0005, (w + e) / 2 + 0.0005, (s + n) / 2 + 0.0005)
            return {
                "features": [{"geometry": geom.__geo_interface__, "properties": {"name": self._d}}]
                if self._d != "flood-risk-zone"
                else []
            }

    def fake_get(url, params=None, timeout=None):
        barrier.wait()
        return Resp(params["dataset"])

    monkeypatch.setattr(requests, "get", fake_get)
    res = mod.UkConstraintsProvider().fetch(aoi, Cache(root=tmp_path, offline=False))
    assert list(res.gdf["dataset"].unique()) == [
        "conservation-area",
        "article-4-direction-area",
        "listed-building-outline",
    ]
    assert [s.name.split(": ")[1] for s in res.sources] == list(res.gdf["dataset"].unique())


def test_restored_site_fetches_climate_lazily(monkeypatch):
    calls: list = []

    def fetch(aoi, cache, *, on_layer=None, only=None, timings=None, height_focus=None):
        calls.append(only)
        return {k: v for k, v in site_layers(aoi).items() if only is None or k in only}

    loaded = Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch)
    assert "climate" not in loaded.layers
    restored = Site.restore(loaded.snapshot())  # a snapshot needs no climate layer
    assert "climate" not in restored.layers and restored.key == loaded.key and restored.timings == {}
    monkeypatch.setattr(pipeline, "fetch_layers", fetch)
    calls.clear()
    d = restored.analyse(restored.square(LON, LAT, 300.0))
    assert d["metrics"]["climate"] and calls == [["climate"]]
