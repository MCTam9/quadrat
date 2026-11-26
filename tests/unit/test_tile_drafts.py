"""Map-tile drafts and the Overpass deadline: pipeline, Site and the SSE stream, all offline.

Overpass is faked per provider (instant, gated on an Event, slow, or failing); the tiles are
the synthetic ones from `_tile_fixtures`, behind the same two HTTP seams the real code uses.
"""

from __future__ import annotations

import json
import threading
import time

import geopandas as gpd
import pytest
from _tile_fixtures import MID_LAT, SEAM_LON, FakeNetwork, aoi
from shapely.geometry import LineString, Point, box

from sce import pipeline
from sce.cache import Cache
from sce.providers import openfreemap_tiles as t
from sce.registry import REGISTRY
from sce.site import Site
from sce.types import LayerResult

FOUR = ["streets", "buildings", "landuse", "amenities"]


@pytest.fixture
def net(monkeypatch):
    return FakeNetwork().install(monkeypatch)


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "c", offline=False)


def _real(layer: str, a) -> LayerResult:
    c = a.geometry.centroid
    gdf = {
        "buildings": lambda: gpd.GeoDataFrame(
            {"height_m": [9.0], "height_source": ["height"]},
            geometry=[box(c.x, c.y, c.x + 40, c.y + 40)],
            crs=a.crs,
        ),
        "streets": lambda: gpd.GeoDataFrame(
            {"highway": ["residential"]}, geometry=[LineString([(c.x, c.y), (c.x + 100, c.y)])], crs=a.crs
        ),
        "landuse": lambda: gpd.GeoDataFrame(
            {"class": ["residential"]}, geometry=[box(c.x - 50, c.y - 50, c.x + 50, c.y + 50)], crs=a.crs
        ),
        "amenities": lambda: gpd.GeoDataFrame({"category": ["food"]}, geometry=[Point(c.x, c.y)], crs=a.crs),
    }[layer]()
    return LayerResult(layer, f"osm_{layer}", gdf=gdf)


def fake_osm(monkeypatch, *, gate: threading.Event | None = None, fail: bool = False, delay: float = 0.0):
    """Replace the four OSM providers' fetch; Overture (which would hit S3) is switched off."""
    for layer in FOUR:

        def fetch(a, cache, layer=layer):
            if fail:
                raise RuntimeError("Overpass is down")
            if gate is not None:
                gate.wait(10)
            if delay:
                time.sleep(delay)
            return _real(layer, a)

        monkeypatch.setattr(REGISTRY.provider(f"osm_{layer}"), "fetch", fetch)
    monkeypatch.setattr(REGISTRY.provider("overture_buildings"), "available", lambda a: False)


class Recorder:
    def __init__(self, release: threading.Event | None = None, release_after: int = 4):
        self.events: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()
        self.release, self.release_after = release, release_after

    def on_draft(self, name, result):
        with self.lock:
            self.events.append(("draft", name, result.provider))
            drafts = sum(1 for e in self.events if e[0] == "draft")
        if self.release is not None and drafts >= self.release_after:
            self.release.set()

    def on_layer(self, name, result):
        with self.lock:
            self.events.append(("layer", name, result.provider if result else "none"))

    def kinds(self):
        return [e[0] for e in self.events]


# -- pipeline ---------------------------------------------------------------------------------


def test_drafts_arrive_before_the_real_layers(monkeypatch, net, cache):
    gate = threading.Event()
    fake_osm(monkeypatch, gate=gate)
    rec = Recorder(release=gate)
    out = pipeline.fetch_layers(
        aoi(), cache, only=FOUR, on_layer=rec.on_layer, on_draft=rec.on_draft, overpass_budget_s=30
    )
    assert rec.kinds() == ["draft"] * 4 + ["layer"] * 4
    drafts = [e for e in rec.events if e[0] == "draft"]
    assert sorted(d[1] for d in drafts) == sorted(FOUR)
    assert all(d[2] == f"tiles_{d[1]}" for d in drafts)
    assert {name: r.provider for name, r in out.items()} == {n: f"osm_{n}" for n in FOUR}


def test_a_draft_is_degraded_and_says_so(monkeypatch, net, cache):
    gate = threading.Event()
    fake_osm(monkeypatch, gate=gate)
    seen = {}

    def on_draft(name, result):
        seen[name] = result
        if len(seen) == 4:
            gate.set()

    pipeline.fetch_layers(aoi(), cache, only=FOUR, on_draft=on_draft)
    assert all(r.degraded and r.notes[0].startswith("From map tiles:") for r in seen.values())


def test_a_draft_that_arrives_after_the_real_layer_is_dropped(monkeypatch, cache):
    FakeNetwork(delay=0.6).install(monkeypatch)  # the tiles are slower than the (instant) Overpass
    fake_osm(monkeypatch)
    rec = Recorder()
    out = pipeline.fetch_layers(aoi(), cache, only=FOUR, on_layer=rec.on_layer, on_draft=rec.on_draft)
    assert rec.kinds() == ["layer"] * 4
    time.sleep(1.5)  # the tile thread finishes now and must find every layer already done
    assert rec.kinds() == ["layer"] * 4
    assert {r.provider for r in out.values()} == {f"osm_{n}" for n in FOUR}


def test_slow_overpass_is_replaced_by_tiles_at_the_deadline(monkeypatch, net, cache):
    gate = threading.Event()  # never opened until the end: Overpass "takes minutes"
    fake_osm(monkeypatch, gate=gate)
    rec = Recorder()
    timings: dict[str, int] = {}
    started = time.perf_counter()
    out = pipeline.fetch_layers(
        aoi(),
        cache,
        only=FOUR,
        on_layer=rec.on_layer,
        on_draft=rec.on_draft,
        overpass_budget_s=0.4,
        timings=timings,
    )
    assert time.perf_counter() - started < 5
    assert {n: r.provider for n, r in out.items()} == {n: f"tiles_{n}" for n in FOUR}
    for r in out.values():
        assert r.degraded
        assert any("Overpass did not answer within 0.4 s" in n for n in r.notes)
        assert r.notes[0].startswith("From map tiles:")
    layer_events = [e for e in rec.events if e[0] == "layer"]
    assert sorted(e[1] for e in layer_events) == sorted(FOUR)  # once each
    assert {e[2] for e in layer_events} == {f"tiles_{n}" for n in FOUR}
    assert set(FOUR) <= set(timings)
    assert all(timings[n] >= 350 for n in FOUR)  # the deadline, not an instant answer

    gate.set()  # Overpass finally answers: the late result is discarded
    time.sleep(0.5)
    assert len([e for e in rec.events if e[0] == "layer"]) == 4
    assert {n: r.provider for n, r in out.items()} == {n: f"tiles_{n}" for n in FOUR}


def test_the_deadline_path_never_fetches_tiles_twice(monkeypatch, net, cache):
    fake_osm(monkeypatch, gate=threading.Event())
    pipeline.fetch_layers(aoi(), cache, only=FOUR, on_draft=lambda *a: None, overpass_budget_s=0.3)
    assert sorted(net.tile_calls) == sorted(set(net.tile_calls))  # each tile once
    assert len(net.tile_calls) == 2
    assert net.tilejson_calls == 1


def test_failed_overpass_falls_back_to_tiles_through_the_registry(monkeypatch, net, cache):
    fake_osm(monkeypatch, fail=True)
    started = time.perf_counter()
    out = pipeline.fetch_layers(aoi(), cache, only=FOUR, on_draft=lambda *a: None, overpass_budget_s=60)
    assert time.perf_counter() - started < 5  # did not wait for the 60 s budget
    assert {n: r.provider for n, r in out.items()} == {n: f"tiles_{n}" for n in FOUR}
    assert all(r.degraded and any("fell back after" in n for n in r.notes) for r in out.values())
    assert len(net.tile_calls) == 2


def test_without_tiles_the_deadline_waits_for_overpass(monkeypatch, cache):
    net = FakeNetwork().install(monkeypatch)

    def down(url):
        raise OSError("tile CDN down")

    monkeypatch.setattr(t, "_get_tile", down)
    fake_osm(monkeypatch, delay=0.8)
    rec = Recorder()
    out = pipeline.fetch_layers(
        aoi(), cache, only=FOUR, on_layer=rec.on_layer, on_draft=rec.on_draft, overpass_budget_s=0.2
    )
    assert {n: r.provider for n, r in out.items()} == {n: f"osm_{n}" for n in FOUR}
    assert rec.kinds() == ["layer"] * 4
    assert net.tilejson_calls >= 1


def test_no_tiles_are_fetched_unless_drafts_or_a_budget_are_asked_for(monkeypatch, net, cache):
    fake_osm(monkeypatch)
    out = pipeline.fetch_layers(aoi(), cache, only=FOUR)
    assert {r.provider for r in out.values()} == {f"osm_{n}" for n in FOUR}
    time.sleep(0.2)
    assert net.tile_calls == [] and net.tilejson_calls == 0


def test_an_override_keeps_that_layer_out_of_the_tile_path(monkeypatch, net, cache):
    fake_osm(monkeypatch)
    rec = Recorder()
    pipeline.fetch_layers(
        aoi(), cache, only=FOUR, override={"buildings": "osm_buildings"}, on_draft=rec.on_draft
    )
    time.sleep(0.3)
    assert rec.events == []


def test_overpass_budget_env(monkeypatch):
    monkeypatch.delenv("SCE_OVERPASS_BUDGET_S", raising=False)
    assert pipeline.overpass_budget_s() == 90.0
    monkeypatch.setenv("SCE_OVERPASS_BUDGET_S", "1")
    assert pipeline.overpass_budget_s() == 1.0
    monkeypatch.setenv("SCE_OVERPASS_BUDGET_S", "soon")
    assert pipeline.overpass_budget_s() == 90.0


# -- Site -------------------------------------------------------------------------------------


@pytest.fixture
def four_layers_only(monkeypatch):
    """Site.load asks for every layer; terrain, LiDAR and friends would need the network."""
    real = pipeline.fetch_layers
    monkeypatch.setattr(
        "sce.pipeline.fetch_layers", lambda a, c, **kw: real(a, c, **{**kw, "only": FOUR}), raising=True
    )


def test_site_load_reports_drafts_then_layers(monkeypatch, net, cache, four_layers_only):
    gate = threading.Event()
    fake_osm(monkeypatch, gate=gate)
    events: list[tuple] = []

    def on_draft(name, result, ms):
        events.append(("draft", name, ms))
        if sum(e[0] == "draft" for e in events) == 4:
            gate.set()

    site = Site.load(
        SEAM_LON,
        MID_LAT,
        200,
        cache=cache,
        on_layer=lambda n, r, ms: events.append(("layer", n, ms)),
        on_draft=on_draft,
        overpass_budget_s=30,
    )
    assert [e[0] for e in events] == ["draft"] * 4 + ["layer"] * 4
    assert all(isinstance(e[2], int) for e in events)
    assert {n: r.provider for n, r in site.layers.items()} == {n: f"osm_{n}" for n in FOUR}


def test_site_load_with_slow_overpass_ends_with_tile_layers_that_survive_a_snapshot(
    monkeypatch, net, cache, four_layers_only
):
    fake_osm(monkeypatch, gate=threading.Event())
    site = Site.load(SEAM_LON, MID_LAT, 200, cache=cache, overpass_budget_s=0.3)
    assert {n: r.provider for n, r in site.layers.items()} == {n: f"tiles_{n}" for n in FOUR}
    back = Site.restore(site.snapshot())
    assert {n: (r.provider, r.degraded) for n, r in back.layers.items()} == {
        n: (f"tiles_{n}", True) for n in FOUR
    }
    # and the analysis of a tile-only site completes, flagged
    monkeypatch.setattr(Site, "climate_layer", lambda self: None)  # not part of this load
    sq = back.square(SEAM_LON, MID_LAT, 150.0)
    out = back.analyse(sq)
    assert out["metrics"]["errors"] == {}
    assert all(v["degraded"] for k, v in out["layers"].items() if k in FOUR)
    assert any("From map tiles" in n for v in out["layers"].values() for n in v["notes"])


def test_site_load_without_the_new_arguments_still_works_with_an_old_fetcher(cache):
    seen = {}

    def old_fetch(a, c, *, on_layer=None, timings=None, only=None, height_focus=None):
        seen["called"] = True
        return {"buildings": _real("buildings", a)}

    Site.load(SEAM_LON, MID_LAT, 200, cache=cache, fetch=old_fetch)
    assert seen


# -- the SSE stream ---------------------------------------------------------------------------

api_main = pytest.importorskip("api.main")
pytest.importorskip("httpx")


class _Store:
    def get(self, key):
        return None

    def put(self, key, data):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path, four_layers_only):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SCE_AUTH_DISABLED", "1")
    monkeypatch.setenv("SCE_OFFLINE", "0")  # Cache() reads it; the HTTP seams are faked
    monkeypatch.setattr("sce.cache.DEFAULT_CACHE", tmp_path / "cache")
    monkeypatch.setattr(api_main, "STORE", _Store())
    api_main.SITES.clear()
    return TestClient(api_main.app)


def _stream(client, **body):
    r = client.post("/api/load", json={"lon": SEAM_LON, "lat": MID_LAT, **body})
    assert r.status_code == 200
    out = []
    for block in r.text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if lines:
            out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


def test_sse_streams_draft_events_before_each_real_event(monkeypatch, net, client):
    gate = threading.Event()
    fake_osm(monkeypatch, gate=gate)
    threading.Timer(1.0, gate.set).start()  # Overpass answers after the tiles have drawn
    ev = _stream(client, half_width_m=400)
    layers = [d for k, d in ev if k == "layer"]
    drafts = [d for d in layers if d.get("draft")]
    assert sorted(d["layer"] for d in drafts) == sorted(FOUR)
    for d in drafts:
        assert d["ok"] is True and d["provider"] == f"tiles_{d['layer']}" and d["features"] > 0
    # same geojson shape as a real layer event
    by = {d["layer"]: d for d in drafts}
    assert set(by["buildings"]["geojson"]) == {"buildings", "context"}
    assert set(by["streets"]["geojson"]) == {"streets"}
    assert set(by["landuse"]["geojson"]) == {"landuse"}
    assert "geojson" not in by["amenities"]
    assert by["buildings"]["geojson"]["buildings"]["features"]
    # every draft precedes its layer's real event, which replaces it
    for name in FOUR:
        idx = [i for i, d in enumerate(layers) if d["layer"] == name and not d.get("update")]
        assert len(idx) == 2
        assert layers[idx[0]].get("draft") and not layers[idx[1]].get("draft")
        assert layers[idx[1]]["provider"] == f"osm_{name}"
    assert ev[-1][0] == "ready"


def test_sse_slow_overpass_ends_in_tile_layers_and_the_load_completes(monkeypatch, net, client):
    fake_osm(monkeypatch, gate=threading.Event())
    monkeypatch.setenv("SCE_OVERPASS_BUDGET_S", "0.5")
    ev = _stream(client, half_width_m=400)
    assert ev[-1][0] == "ready"
    finals = {d["layer"]: d for k, d in ev if k == "layer" and not d.get("draft") and not d.get("update")}
    assert {n: d["provider"] for n, d in finals.items()} == {n: f"tiles_{n}" for n in FOUR}
    assert all(d["ok"] for d in finals.values())


def test_sse_emits_no_draft_after_the_real_layer(monkeypatch, client):
    FakeNetwork(delay=0.7).install(monkeypatch)
    fake_osm(monkeypatch)
    ev = _stream(client, half_width_m=400)
    layers = [d for k, d in ev if k == "layer"]
    assert not [d for d in layers if d.get("draft")]
    assert {d["provider"] for d in layers if not d.get("update")} == {f"osm_{n}" for n in FOUR}
    time.sleep(1.2)  # nothing can arrive afterwards: the stream has ended
