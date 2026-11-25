"""The web API, offline: auth, SSE load, clip-backed analyse/preview, zip export."""

from __future__ import annotations

import importlib.util
import io
import json
import time
import zipfile

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, box

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.main as api_main  # noqa: E402
from sce.types import LayerResult, Source  # noqa: E402

LON, LAT = -0.1, 51.5
SID = api_main.site_key(LON, LAT)  # no half_width_m on load -> maximum padding


def _layers(aoi):
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    blds = gpd.GeoDataFrame(
        {
            "height_m": [9.0, np.nan, 30.0],
            "height_source": ["height", "", "height"],
            "building": ["residential", "yes", "office"],
            "building:levels": ["3", None, "10"],
        },
        geometry=[
            box(cx - 50, cy - 50, cx - 30, cy - 30),
            box(cx + 100, cy + 100, cx + 130, cy + 130),
            box(cx + 1000, cy + 1000, cx + 1040, cy + 1040),
        ],
        crs=aoi.crs,
    )
    g = nx.MultiDiGraph(crs=aoi.crs)
    g.add_node(1, x=cx, y=cy)
    g.add_node(2, x=cx + 100, y=cy)
    g.add_edge(1, 2, length=100.0)
    streets = gpd.GeoDataFrame(
        {"highway": ["residential"]}, geometry=[LineString([(cx, cy), (cx + 100, cy)])], crs=aoi.crs
    )
    minx, miny, maxx, maxy = aoi.bounds_metric
    res = 30.0
    n = int((maxx - minx) / res)
    yy, xx = np.mgrid[0:n, 0:n]
    terrain = {
        "array": (xx * 0.5 + yy * 0.2).astype(float),
        "transform": Affine(res, 0, minx, 0, -res, maxy),
        "crs": aoi.crs,
        "nodata": None,
        "res": (res, res),
    }
    osm = Source("OpenStreetMap contributors", "https://www.openstreetmap.org/copyright", "ODbL 1.0")
    landuse = gpd.GeoDataFrame(
        {"class": ["park", "residential"]},
        geometry=[box(cx - 200, cy - 200, cx, cy), box(cx, cy, cx + 200, cy + 200)],
        crs=aoi.crs,
    )
    constraints = gpd.GeoDataFrame(
        {"dataset": ["conservation-area"], "name": ["Test CA"]},
        geometry=[box(cx - 100, cy - 100, cx + 100, cy + 100)],
        crs=aoi.crs,
    )
    hours = 3 * 8760
    t = np.arange(hours)
    hourly = {
        "time": np.datetime64("2021-01-01T00:00") + t.astype("timedelta64[h]"),
        "temperature_c": 10
        + 8 * np.sin(2 * np.pi * (t / 8760 - 0.3))
        + 4 * np.sin(2 * np.pi * (t % 24) / 24),
        "dew_point_c": 5 + 6 * np.sin(2 * np.pi * (t / 8760 - 0.3)),
        "relative_humidity_pct": np.full(hours, 75.0),
        "pressure_pa": np.full(hours, 101300.0),
        "ghi_wm2": np.clip(400 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "dni_wm2": np.clip(300 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "dhi_wm2": np.clip(100 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "wind_speed_ms": np.full(hours, 4.0),
        "wind_direction_deg": np.full(hours, 225.0),
        "cloud_cover_pct": np.full(hours, 60.0),
        "precipitation_mm": np.full(hours, 0.1),
    }
    climate = LayerResult(
        "climate",
        "fake",
        data={
            "hourly": hourly,
            "timezone": {"name": "Europe/London", "standard_offset_h": 0.0, "approximate": False},
            "elevation_m": 16.0,
            "grid_point_lonlat": [LON, LAT],
            "period": "2021-01-01 to 2023-12-31",
        },
        sources=[Source("Open-Meteo ERA5 archive", "https://open-meteo.com", "CC BY 4.0")],
    )
    return {
        "climate": climate,
        "landuse": LayerResult("landuse", "fake", gdf=landuse, sources=[osm]),
        "constraints": LayerResult("constraints", "fake", gdf=constraints),
        "buildings": LayerResult("buildings", "fake", gdf=blds, coverage=2 / 3, sources=[osm]),
        "streets": LayerResult("streets", "fake", gdf=streets, data={"graph": g}, sources=[osm]),
        "terrain": LayerResult("terrain", "fake", raster=terrain, data={}),
    }


@pytest.fixture
def calls(monkeypatch):
    rec: list = []

    def fake_fetch(aoi, cache, *a, on_layer=None, **kw):
        rec.append(aoi)
        layers = _layers(aoi)
        for name, res in layers.items():
            if on_layer:
                on_layer(name, res)
        return layers

    monkeypatch.setattr("sce.pipeline.fetch_layers", fake_fetch)
    api_main.SITES.clear()
    return rec


@pytest.fixture
def client(monkeypatch, calls):
    monkeypatch.setenv("SCE_AUTH_DISABLED", "1")
    return TestClient(api_main.app)


def _body(hw=300.0, **kw):
    return {"site_id": SID, "lon": LON, "lat": LAT, "half_width_m": hw, **kw}


def _load(client):
    r = client.post("/api/load", json={"lon": LON, "lat": LAT})
    assert r.status_code == 200
    return r


def _events(text):
    out = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if lines:
            out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


def test_health_needs_no_auth(monkeypatch):
    monkeypatch.delenv("SCE_AUTH_DISABLED", raising=False)
    r = TestClient(api_main.app).get("/api/health")
    assert r.json()["ok"] is True and "version" in r.json()


def test_401_without_token(monkeypatch, calls):
    monkeypatch.delenv("SCE_AUTH_DISABLED", raising=False)
    r = TestClient(api_main.app).post("/api/load", json={"lon": LON, "lat": LAT})
    assert r.status_code == 401 and "error" in r.json()
    assert not calls


@pytest.fixture
def rsa_auth(monkeypatch, calls):
    monkeypatch.delenv("SCE_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.example")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://app.example")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(api_main, "_jwks_client", lambda: _Client())

    def mint(**over):
        now = int(time.time())
        claims = {
            "sub": "u",
            "iss": "https://clerk.example",
            "azp": "https://app.example",
            "exp": now + 60,
            "nbf": now - 5,
            **over,
        }
        return jwt.encode(claims, key, algorithm="RS256")

    return mint


def test_valid_token_accepted(rsa_auth):
    c = TestClient(api_main.app)
    r = c.post("/api/load", json={"lon": LON, "lat": LAT}, headers={"Authorization": f"Bearer {rsa_auth()}"})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "over",
    [{"exp": 1}, {"iss": "https://evil"}, {"azp": "https://evil"}, {"nbf": 4_000_000_000}],
)
def test_bad_claims_rejected(rsa_auth, over):
    c = TestClient(api_main.app)
    r = c.post(
        "/api/load",
        json={"lon": LON, "lat": LAT},
        headers={"Authorization": f"Bearer {rsa_auth(**over)}"},
    )
    assert r.status_code == 401


def test_load_streams_layers_then_ready(client, calls):
    ev = _events(_load(client).text)
    kinds = [k for k, _ in ev]
    assert kinds == ["layer"] * 6 + ["ready"]
    bld = next(d for k, d in ev if k == "layer" and d["layer"] == "buildings")
    assert bld["features"] == 3 and bld["ok"]
    ready = ev[-1][1]
    assert ready["site_id"] == SID and ready["padded_half_width_m"] == 1500
    assert ready["epsg"].startswith("EPSG:") and len(ready["bbox_wgs84"]) == 4
    assert calls[0].name == "padded" and calls[0].radius_m == 1500


def test_load_reports_failure(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr("sce.pipeline.fetch_layers", boom)
    ev = _events(_load(client).text)
    assert ev == [("error", {"error": "could not load data for this location"})]


def test_validation(client):
    assert client.post("/api/load", json={"lon": 200, "lat": 0}).status_code == 422
    _load(client)
    assert client.post("/api/analyse", json=_body(hw=10)).status_code == 422
    assert client.post("/api/analyse", json=_body(hw=1001)).status_code == 422


def test_analyse(client):
    _load(client)
    r = client.post("/api/analyse", json=_body())
    assert r.status_code == 200
    d = r.json()
    json.dumps(d, allow_nan=False)
    assert "gsi" in d["metrics"]["fabric"] and "fsi" in d["metrics"]["fabric"]
    sq = d["aoi"]["square"]
    assert sq["type"] == "Polygon"
    assert abs(sq["coordinates"][0][0][0] - LON) < 0.01
    assert set(d["layers"]["buildings"]) == {"provider", "coverage", "degraded", "notes"}
    assert d["layers"]["buildings"]["coverage"] == pytest.approx(0.5)
    assert "graph" not in json.dumps(d["layers"])


def test_409_unknown_site_and_outside(client):
    assert client.post("/api/analyse", json=_body()).json() == {"error": "reload"}
    assert client.post("/api/preview", json=_body()).status_code == 409
    _load(client)
    far = _body() | {"lon": LON + 0.05}
    assert client.post("/api/analyse", json=far).status_code == 409
    assert client.post("/api/preview", json=far).status_code == 409


def test_preview(client):
    _load(client)
    d = client.post("/api/preview", json=_body()).json()
    assert d["square"]["type"] == "Feature"
    feats = d["buildings"]["features"]
    assert len(feats) == 2
    x, y = feats[0]["geometry"]["coordinates"][0][0]
    assert abs(x - LON) < 0.01 and abs(y - LAT) < 0.01
    assert {f["properties"]["height_m"] for f in feats} == {9.0, None}
    assert d["streets"]["features"][0]["properties"] == {"highway": "residential"}
    assert len(str(x).split(".")[1]) <= 6


def test_preview_layers(client):
    _load(client)
    d = client.post("/api/preview", json=_body()).json()
    props = {f["properties"]["building"]: f["properties"] for f in d["buildings"]["features"]}
    assert props["residential"]["levels"] == 3.0 and props["yes"]["levels"] is None
    assert {f["properties"]["class"] for f in d["landuse"]["features"]} == {"green_space", "residential"}
    assert d["constraints"]["features"][0]["properties"] == {
        "dataset": "conservation-area",
        "name": "Test CA",
    }
    assert d["contour_interval_m"] > 0
    assert d["contours"]["features"], "a tilted plane must produce contours"
    assert all("elevation_m" in f["properties"] for f in d["contours"]["features"])


def test_climate_endpoint(client):
    pytest.importorskip("sce.climate")
    assert client.post("/api/climate", json={"site_id": "nope"}).status_code == 409
    _load(client)
    r = client.post("/api/climate", json={"site_id": SID})
    assert r.status_code == 200
    d = r.json()
    assert len(d["typical_year"]["hourly"]["temperature_c"]) == 8760
    assert len(d["monthly"]) == 12
    assert d["timezone"]["name"] == "Europe/London"
    json.dumps(d, allow_nan=False)


def test_export_zip_from_cache(client, calls):
    _load(client)
    r = client.post("/api/export", json=_body(formats=["dxf"], report=False))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "sce-51.50000--0.10000-600m.zip" in r.headers["content-disposition"]
    assert len(calls) == 1  # no second fetch
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert {"dossier.json", "README.txt", "georef.json", "site.dxf"} <= set(names)
    readme = zipfile.ZipFile(io.BytesIO(r.content)).read("README.txt").decode()
    assert "ODbL" in readme and "EPSG:" in readme


def test_export_without_cache_fetches_inner(client, calls):
    r = client.post("/api/export", json={**_body(), "site_id": None, "formats": ["dxf"], "report": False})
    assert r.status_code == 200
    assert calls[-1].name == "site" and calls[-1].radius_m == 300


@pytest.mark.skipif(importlib.util.find_spec("sce.export.geojson") is None, reason="geojson exporter missing")
def test_export_geojson(client):
    _load(client)
    r = client.post("/api/export", json=_body(formats=["dxf", "geojson"], report=False))
    assert "site.geojson" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()


def test_export_unknown_format(client):
    r = client.post("/api/export", json=_body(formats=["docx"]))
    assert r.status_code == 400 and "docx" in r.json()["error"]


def test_lru_evicts_oldest():
    store = api_main._SiteStore(2)
    for k in "abc":
        store.put(k, (None, {}))
    assert store.get("a") is None and store.get("c") is not None


def test_padded_fetch_scales_with_square(client):
    assert api_main.padded_half_width(None) == 1500
    assert api_main.padded_half_width(100) == 750
    assert api_main.padded_half_width(600) == 1100
    assert api_main.padded_half_width(1000) == 1500
    r = client.post("/api/load", json={"lon": LON, "lat": LAT, "half_width_m": 300})
    ready = [ln for ln in r.text.splitlines() if ln.startswith("data:")][-1]
    assert '"padded_half_width_m": 800' in ready
