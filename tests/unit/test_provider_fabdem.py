"""FABDEM provider tests. Zero network: local tiles only.

Covers the opt-in / non-commercial contract in CONTRIBUTING.md and the honest
"no automated download" behaviour described in the module docstring of
sce/providers/terrain_fabdem.py.
"""

from __future__ import annotations

import re

import numpy as np
import pytest
import rasterio
from affine import Affine

from sce.aoi import AOI
from sce.providers.terrain_fabdem import FabdemTerrainProvider, _tile_name


def _aoi() -> AOI:
    # Centred so its 1x1 degree tile is unambiguous: N51E000.
    return AOI.from_point(0.4, 51.4, 300.0, name="fabdem-test")


def test_commercial_ok_is_false():
    assert FabdemTerrainProvider.commercial_ok is False


def test_declares_terrain_layer_and_rank_below_copernicus():
    from sce.providers.terrain_copernicus import CopernicusTerrainProvider

    assert FabdemTerrainProvider.name == "fabdem"
    assert FabdemTerrainProvider.layer == "terrain"
    assert FabdemTerrainProvider.rank > CopernicusTerrainProvider.rank


def test_licence_string_mentions_cc_by_nc_sa():
    assert "NC" in FabdemTerrainProvider.licence
    assert "CC BY-NC-SA" in FabdemTerrainProvider.licence


def test_available_is_false_without_env_var(monkeypatch):
    monkeypatch.delenv("SCE_FABDEM_DIR", raising=False)
    provider = FabdemTerrainProvider()
    assert provider.available(_aoi()) is False


def test_available_is_false_when_dir_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("SCE_FABDEM_DIR", str(tmp_path / "does-not-exist"))
    provider = FabdemTerrainProvider()
    assert provider.available(_aoi()) is False


def test_fetch_without_env_var_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("SCE_FABDEM_DIR", raising=False)
    provider = FabdemTerrainProvider()
    with pytest.raises(RuntimeError, match=re.escape("SCE_FABDEM_DIR")):
        provider.fetch(_aoi(), cache=None)


def test_fetch_with_empty_dir_names_the_missing_tile(monkeypatch, tmp_path):
    monkeypatch.setenv("SCE_FABDEM_DIR", str(tmp_path))
    provider = FabdemTerrainProvider()
    with pytest.raises(RuntimeError, match=re.escape("N51E000_FABDEM_V1-2.tif")):
        provider.fetch(_aoi(), cache=None)


def _write_fake_tile(path, lat: int, lon: int) -> None:
    """A 1x1 degree bare-earth-shaped tile: a gentle plane, WGS84, EGM-ish."""
    n = 120  # ~30m at the equator over 1 degree
    transform = Affine(1.0 / n, 0.0, lon, 0.0, -1.0 / n, lat + 1.0)
    xs = np.arange(n)
    array = np.tile(xs.astype(np.float32), (n, 1))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=n,
        width=n,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(array, 1)


def test_fetch_with_local_tile_returns_dtm_bare_earth(monkeypatch, tmp_path):
    aoi = _aoi()
    lon0, lat0 = 0, 51
    _write_fake_tile(tmp_path / _tile_name(lat0, lon0), lat0, lon0)
    monkeypatch.setenv("SCE_FABDEM_DIR", str(tmp_path))

    provider = FabdemTerrainProvider()
    assert provider.available(aoi) is True

    result = provider.fetch(aoi, cache=None)
    assert result.raster is not None
    assert result.data["terrain_model"] == "DTM"
    assert result.sources[0].commercial_ok is False
    assert "CC BY-NC-SA" in result.sources[0].licence
    valid = result.raster.array
    assert np.isfinite(valid).any()


def test_tile_name_format():
    assert _tile_name(51, 0) == "N51E000_FABDEM_V1-2.tif"
    assert _tile_name(-5, -10) == "S05W010_FABDEM_V1-2.tif"
