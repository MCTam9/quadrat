"""Site snapshots and the snapshot stores, offline."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest
from _site_fixtures import LAT, LON, site_layers

from sce import store as store_mod
from sce.raster import SiteRaster
from sce.site import Site
from sce.store import BlobStore, LocalStore, default_store, pathname_for

TOKEN = "vercel_blob_rw_AbC123_secretsecret"


@pytest.fixture
def site():
    def fetch(aoi, cache, **kw):
        return site_layers(aoi)

    return Site.load(LON, LAT, 300.0, cache=object(), fetch=fetch)


def _dump(obj):
    return json.dumps(obj, sort_keys=True)


def test_round_trip_gives_identical_views(site):
    restored = Site.restore(site.snapshot())
    assert restored.key == site.key
    assert restored.outer.geometry.equals(site.outer.geometry) and restored.outer.crs == site.outer.crs
    square = site.square(LON, LAT, 300.0)
    sq2 = restored.square(LON, LAT, 300.0)
    assert _dump(restored.analyse(sq2)) == _dump(site.analyse(square))
    assert _dump(restored.preview(sq2)) == _dump(site.preview(square))
    assert restored.climate() == site.climate()


def test_layers_survive_field_by_field(site):
    restored = Site.restore(site.snapshot())
    assert list(restored.layers) == list(site.layers)
    for name, a in site.layers.items():
        b = restored.layers[name]
        assert (a.layer, a.provider, a.coverage, a.degraded, a.notes, a.findings) == (
            b.layer,
            b.provider,
            b.coverage,
            b.degraded,
            b.notes,
            b.findings,
        )
        assert [s.to_dict() for s in a.sources] == [s.to_dict() for s in b.sources]
        if a.gdf is not None:
            assert b.gdf.crs == a.gdf.crs and len(b.gdf) == len(a.gdf)
            assert b.gdf.geometry.geom_equals(a.gdf.geometry).all()
    ta, tb = site.layers["terrain"].raster, restored.layers["terrain"].raster
    assert np.array_equal(ta.array, tb.array, equal_nan=True)
    assert ta.transform == tb.transform and ta.array.dtype == tb.array.dtype
    assert np.array_equal(ta.inside(), tb.inside())
    g1, g2 = site.layers["streets"].data["graph"], restored.layers["streets"].data["graph"]
    assert set(g1.nodes) == set(g2.nodes) and set(g1.edges) == set(g2.edges)


def test_integer_raster_with_sentinel_nodata_round_trips(site):
    old = site.layers["terrain"].raster
    arr = (np.arange(old.array.size).reshape(old.array.shape) % 5).astype(np.uint8)
    r = SiteRaster.from_array(arr, old.transform, old.crs, square=old.square, nodata=0, kind="lc")
    site.layers["terrain"] = replace(site.layers["terrain"], raster=r)
    back = Site.restore(site.snapshot()).layers["terrain"].raster
    assert back.array.dtype == np.uint8 and back.nodata == 0 and back.kind == "lc"
    assert back.share_known() == r.share_known()


def test_unreadable_snapshot_raises():
    with pytest.raises(Exception):  # noqa: B017
        Site.restore(b"junk")


def test_local_store_round_trip(tmp_path):
    st = LocalStore(tmp_path)
    assert st.get("-0.1,51.5,1500") is None
    st.put("-0.1,51.5,1500", b"abc")
    assert st.get("-0.1,51.5,1500") == b"abc"
    assert (tmp_path / "sites" / "-0.1_51.5_1500.zip").exists()


def test_default_store_selection(monkeypatch, tmp_path):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("SCE_SNAPSHOTS", raising=False)
    monkeypatch.setenv("SCE_CACHE", str(tmp_path))
    assert isinstance(default_store(), LocalStore)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", TOKEN)
    assert isinstance(default_store(), BlobStore)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "garbage")
    assert default_store() is None
    monkeypatch.setenv("SCE_SNAPSHOTS", "0")
    assert default_store() is None


class _Resp:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


class _Session:
    def __init__(self, resp=None, exc=None):
        self.calls, self.resp, self.exc = [], resp or _Resp(), exc

    def _do(self, verb, url, **kw):
        self.calls.append((verb, url, kw))
        if self.exc:
            raise self.exc
        return self.resp

    def put(self, url, **kw):
        return self._do("put", url, **kw)

    def get(self, url, **kw):
        return self._do("get", url, **kw)

    def post(self, url, **kw):
        return self._do("post", url, **kw)


def test_blob_put_request_shape():
    s = _Session()
    BlobStore(TOKEN, session=s).put("-0.1,51.5,1500", b"zipbytes")
    verb, url, kw = s.calls[0]
    assert (verb, url) == ("put", "https://vercel.com/api/blob/")
    assert kw["params"] == {"pathname": "sites/-0.1_51.5_1500.zip"}
    assert kw["params"]["pathname"] == pathname_for("-0.1,51.5,1500")
    assert kw["data"] == b"zipbytes" and kw["timeout"] == 20.0
    h = kw["headers"]
    assert h["authorization"] == f"Bearer {TOKEN}"
    assert h["x-vercel-blob-access"] == "private"
    assert h["x-add-random-suffix"] == "0" and h["x-allow-overwrite"] == "1"
    assert h["x-ttl-days"] == "7" and h["x-api-version"]


def test_blob_get_request_shape_and_results():
    s = _Session(_Resp(200, b"data"))
    assert BlobStore(TOKEN, session=s).get("k") == b"data"
    _, url, kw = s.calls[0]
    assert url == "https://abc123.private.blob.vercel-storage.com/sites/k.zip"
    assert kw["headers"]["authorization"] == f"Bearer {TOKEN}" and kw["timeout"] == 20.0
    assert BlobStore(TOKEN, session=_Session(_Resp(404))).get("k") is None
    assert BlobStore(TOKEN, session=_Session(_Resp(500))).get("k") is None


def test_blob_failures_only_warn(caplog):
    b = BlobStore(TOKEN, session=_Session(exc=TimeoutError("slow")))
    assert b.get("k") is None
    b.put("k", b"x")
    b.delete("k")
    assert "blob put failed" in caplog.text
    BlobStore(TOKEN, session=_Session(_Resp(403))).put("k", b"x")


def test_sanitise_key():
    assert store_mod.sanitise_key("../../etc/passwd") == "etc_passwd"
