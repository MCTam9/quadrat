"""EA LiDAR provider: availability and a fetch against a monkeypatched WCS."""

from __future__ import annotations

import numpy as np
import pytest
from affine import Affine
from rasterio.io import MemoryFile

from sce.aoi import AOI
from sce.cache import Cache
from sce.providers.height_ea_lidar import EaLidarBuildingHeightProvider
from sce.providers.height_ghsl import GhslBuildingHeightProvider


def _aoi(lon: float, lat: float, r: float = 150.0) -> AOI:
    return AOI.from_point(lon, lat, r, name="t")


def test_rank_runs_before_ghsl():
    assert EaLidarBuildingHeightProvider.rank < GhslBuildingHeightProvider.rank
    assert EaLidarBuildingHeightProvider.layer == "building_height"


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [(-0.128, 51.507, True), (2.35, 48.86, False), (-3.19, 55.95, False), (-3.2, 51.48, False)],
)
def test_available(lon, lat, expected):
    assert EaLidarBuildingHeightProvider().available(_aoi(lon, lat)) is expected


def _tif(x0: float, y1: float, dsm_value: float, dtm_value: float, which: str) -> bytes:
    n = 1000
    arr = np.full((n, n), dtm_value, dtype=np.float32)
    if which == "dsm":
        arr[:] = dsm_value
        arr[:5, :5] = -3.4028234663852886e38  # nodata corner
    with MemoryFile() as mf:
        with mf.open(
            driver="GTiff",
            width=n,
            height=n,
            count=1,
            dtype="float32",
            crs="EPSG:27700",
            transform=Affine(1, 0, x0, 0, -1, y1),
            nodata=-3.4028234663852886e38,
        ) as ds:
            ds.write(arr, 1)
        return mf.read()


def test_fetch_builds_ndsm(monkeypatch, tmp_path):
    import requests

    class Resp:
        def __init__(self, content, url):
            self.content, self.url = content, url

        def raise_for_status(self):
            pass

    def fake_get(url, params=None, timeout=None):
        e = params["subset"][0][2:-1].split(",")
        n = params["subset"][1][2:-1].split(",")
        x0, y1 = int(e[0]), int(n[1])
        which = "dsm" if "surface" in url else "dtm"
        return Resp(_tif(x0, y1, 112.0, 100.0, which), url)

    monkeypatch.setattr(requests, "get", fake_get)
    res = EaLidarBuildingHeightProvider().fetch(_aoi(-0.128, 51.507), Cache(tmp_path, offline=False))
    assert res.layer == "building_height"
    r = res.raster
    assert r.kind == "ndsm" and res.data["kind"] == "ndsm"
    assert r.crs == _aoi(-0.128, 51.507).crs
    assert r.res == (1.0, 1.0)
    finite = r.array[np.isfinite(r.array)]
    assert finite.min() >= 0.0
    assert np.median(finite) == pytest.approx(12.0, abs=0.01)
    assert res.data["mean_height_m"] == pytest.approx(12.0, abs=0.01)
    assert res.coverage > 0.99
    assert "Open Government Licence" in res.sources[0].licence


def test_stalled_service_gives_up_within_budget(monkeypatch, tmp_path):
    """A hung WCS must fail fast so the registry falls through to GHSL."""
    import time

    from sce.aoi import AOI
    from sce.cache import Cache
    from sce.providers import height_ea_lidar as mod

    monkeypatch.setenv("SCE_LIDAR_BUDGET_S", "0.3")
    monkeypatch.setattr(mod, "_fetch_tile", lambda *a, **k: time.sleep(2))
    aoi = AOI.from_point(-0.1276, 51.5072, 200.0)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="pending"):
        mod.EaLidarBuildingHeightProvider().fetch(aoi, Cache(tmp_path))
    assert time.monotonic() - t0 < 1.5
