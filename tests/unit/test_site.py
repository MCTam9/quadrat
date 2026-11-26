"""Site: one padded fetch, any square inside it, every view through one clip. Offline."""

from __future__ import annotations

import json

import pytest
from _site_fixtures import LAT, LON, site_layers

from sce.site import OutsideSite, Site, padded_half_width


@pytest.fixture
def fetched():
    calls = []

    def fetch(aoi, cache, *, on_layer=None, only=None, timings=None, height_focus=None):
        calls.append({"aoi": aoi, "only": only, "height_focus": height_focus})
        layers = {k: v for k, v in site_layers(aoi).items() if only is None or k in only}
        for name, res in layers.items():
            if on_layer:
                on_layer(name, res)
        return layers

    return fetch, calls


@pytest.fixture
def site(fetched, tmp_path):
    fetch, _ = fetched
    return Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch)


def test_load_pads_the_fetch_and_reports_ready(fetched):
    fetch, calls = fetched
    seen = []
    site = Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch, on_layer=lambda n, r, ms: seen.append(n))
    assert calls[0]["aoi"].radius_m == padded_half_width(300.0) == 600.0
    assert "buildings" in seen
    ready = site.ready()
    assert ready["site_id"] == site.key and ready["epsg"].startswith("EPSG:")
    assert ready["padded_half_width_m"] == 600.0


def test_square_outside_the_site_raises(site):
    with pytest.raises(OutsideSite):
        site.square(LON + 0.05, LAT, 300.0)


def test_one_clip_per_square_shared_by_every_view(site, monkeypatch):
    import sce.site as mod

    clips = []
    real = mod.clip_layers
    monkeypatch.setattr(mod, "clip_layers", lambda *a: clips.append(1) or real(*a))
    sq = site.square(LON, LAT, 300.0)
    site.analyse(sq)
    site.preview(sq)
    assert len(clips) == 1


def test_analyse_is_json_safe_with_height_shares(site):
    d = site.analyse(site.square(LON, LAT, 300.0))
    json.dumps(d, allow_nan=False)
    shares = d["metrics"]["fabric"]["height_source_shares"]
    assert sum(shares.values()) == pytest.approx(1.0)
    assert isinstance(d["layers"]["buildings"]["notes"], list)
    assert d["aoi"]["square"]["type"] == "Polygon"


def test_preview_has_every_layer_with_building_use_and_context(site):
    d = site.preview(site.square(LON, LAT, 300.0))
    json.dumps(d, allow_nan=False)
    for key in ("buildings", "streets", "landuse", "contours", "constraints", "context"):
        assert d[key]["type"] == "FeatureCollection"
    props = [f["properties"] for f in d["buildings"]["features"]]
    assert {"use", "use_source", "height_source"} <= set(props[0])
    # The fixture's third building sits ~1 km out: outside the square, outside the 150 m ring.
    assert len(d["buildings"]["features"]) == 2
    assert d["contour_interval_m"] > 0


def test_climate_summary_cached(site):
    first = site.climate()
    assert len(first["typical_year"]["hourly"]["temperature_c"]) == 8760
    assert site.climate() is first


def test_export_writes_bundle_with_readme_and_georef(site, tmp_path):
    files = site.export(site.square(LON, LAT, 300.0), ["dxf"], tmp_path / "out", report=False)
    names = [f.name for f in files]
    assert names[0] == "README.txt"
    assert {"dossier.json", "georef.json", "georef.prj"} <= set(names)
    assert any(n.endswith(".dxf") for n in names)
    readme = (tmp_path / "out" / "README.txt").read_text()
    assert "OpenStreetMap" in readme and "dxf" in readme


def test_export_rejects_unknown_format(site, tmp_path):
    with pytest.raises(ValueError, match="unknown formats"):
        site.export(site.square(LON, LAT, 300.0), ["dwg"], tmp_path)


def test_for_square_fetches_exactly_the_square(fetched):
    fetch, calls = fetched
    site = Site.for_square(LON, LAT, 300.0, cache=object(), fetch=fetch)
    assert calls[-1]["aoi"].radius_m == 300.0
    assert site.square(LON, LAT, 300.0).area_m2 == pytest.approx(360_000.0, rel=1e-6)
