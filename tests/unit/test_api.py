"""The web API, offline: auth, SSE load, clip-backed analyse/preview, zip export."""

from __future__ import annotations

import importlib.util
import io
import json
import threading
import time
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
jwt = pytest.importorskip("jwt")
from _site_fixtures import site_layers as _layers  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.main as api_main  # noqa: E402

LON, LAT = -0.1, 51.5
SID = api_main.site_key(LON, LAT)  # no half_width_m on load -> maximum padding


class MemoryStore:
    """In-memory snapshot store that counts writes."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.puts = 0

    def get(self, key):
        return self.blobs.get(key)

    def put(self, key, data):
        self.blobs[key] = data
        self.puts += 1


@pytest.fixture
def store(monkeypatch):
    st = MemoryStore()
    monkeypatch.setattr(api_main, "STORE", st)
    return st


@pytest.fixture
def calls(monkeypatch, store):
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


def test_issuer_and_jwks_come_from_the_publishable_key(monkeypatch):
    import base64

    pk = "pk_test_" + base64.b64encode(b"able-mole-12.clerk.accounts.dev$").decode().rstrip("=")
    for k in ("CLERK_ISSUER", "CLERK_JWKS_URL", "CLERK_PUBLISHABLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", pk)
    assert api_main._clerk_issuer() == "https://able-mole-12.clerk.accounts.dev"
    assert api_main._jwks_url() == "https://able-mole-12.clerk.accounts.dev/.well-known/jwks.json"
    monkeypatch.setenv("CLERK_ISSUER", "https://clerk.custom.example")
    assert api_main._clerk_issuer() == "https://clerk.custom.example"


def test_garbage_publishable_key_gives_no_issuer():
    assert api_main._issuer_from_publishable_key("pk_test_%%%") is None
    assert api_main._issuer_from_publishable_key("nonsense") is None


def test_authorized_parties_default_to_this_deployment(monkeypatch):
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES", raising=False)
    monkeypatch.setenv("VERCEL_URL", "quadrat-abc.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "quadrat.vercel.app")
    monkeypatch.delenv("VERCEL_BRANCH_URL", raising=False)
    assert api_main._authorized_parties() == ["https://quadrat-abc.vercel.app", "https://quadrat.vercel.app"]
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://a.example, https://b.example")
    assert api_main._authorized_parties() == ["https://a.example", "https://b.example"]


@pytest.mark.parametrize(
    ("azp", "status"), [("https://quadrat-home.example", 200), ("https://evil.example", 401)]
)
def test_token_from_the_domain_the_user_opened(rsa_auth, monkeypatch, azp, status):
    """Any domain or alias of the project works: the page's own origin is an authorised party."""
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES")
    for k in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        monkeypatch.delenv(k, raising=False)
    r = TestClient(api_main.app).post(
        "/api/load",
        json={"lon": LON, "lat": LAT},
        headers={"Authorization": f"Bearer {rsa_auth(azp=azp)}", "x-forwarded-host": "quadrat-home.example"},
    )
    assert r.status_code == status


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
    assert "quadrat-51.50000--0.10000-600m.zip" in r.headers["content-disposition"]
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
    from types import SimpleNamespace

    store = api_main._SiteStore(2)
    for k in "abc":
        store.put(SimpleNamespace(key=k))
    assert store.get("a") is None and store.get("c") is not None


def test_padded_fetch_scales_with_square(client):
    assert api_main.padded_half_width(None) == 1500
    assert api_main.padded_half_width(100) == 750
    assert api_main.padded_half_width(600) == 1100
    assert api_main.padded_half_width(1000) == 1500
    r = client.post("/api/load", json={"lon": LON, "lat": LAT, "half_width_m": 300})
    ready = [ln for ln in r.text.splitlines() if ln.startswith("data:")][-1]
    assert '"padded_half_width_m": 800' in ready


# -- snapshots: a cold instance restores the site instead of answering 409 ---------------


def test_load_writes_a_snapshot_and_a_cold_instance_restores_it(client, store):
    _load(client)
    assert store.puts == 1  # written before `ready`
    warm = client.post("/api/analyse", json=_body()).json()
    api_main.SITES.clear()
    r = client.post("/api/analyse", json=_body())
    assert r.status_code == 200 and r.json() == warm
    assert client.post("/api/preview", json=_body()).status_code == 200
    api_main.SITES.clear()
    assert client.post("/api/climate", json={"site_id": SID}).status_code == 200


def test_unknown_site_is_still_409(client):
    assert client.post("/api/analyse", json=_body()).status_code == 409


def test_load_of_a_stored_site_skips_the_fetch(client, store, calls):
    _load(client)
    assert store.puts == 1  # written before `ready`
    n = len(calls)
    api_main.SITES.clear()
    r = _load(client)
    events = _events(r.text)
    assert len(calls) == n and store.puts == 1  # a restored site is not written back
    assert events[-1][0] == "ready" and events[-1][1]["site_id"] == SID
    assert {d["layer"] for e, d in events if e == "layer"} >= {"buildings", "terrain", "streets"}


def test_store_failures_are_swallowed(client, store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(store, "get", boom)
    monkeypatch.setattr(store, "put", boom)
    r = _load(client)
    assert _events(r.text)[-1][0] == "ready"
    assert client.post("/api/analyse", json=_body()).status_code == 200
    api_main.SITES.clear()
    assert client.post("/api/analyse", json=_body()).status_code == 409


def test_corrupt_snapshot_is_a_miss(client, store):
    store.blobs[SID] = b"not a zip"
    assert client.post("/api/analyse", json=_body()).status_code == 409


def test_slow_snapshot_write_is_capped_and_ready_still_arrives(client, store, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(api_main, "SNAPSHOT_WAIT_S", 0.2)
    monkeypatch.setattr(store, "put", lambda key, data: release.wait(10))
    try:
        r = _load(client)
        assert _events(r.text)[-1][0] == "ready"
    finally:
        release.set()
