"""Test harness: blocks network access by default and freezes external caches.

Every test runs offline unless explicitly marked `@pytest.mark.live`. This is
what lets `tests/fixtures/osmnx/` (committed, frozen HTTP responses) stand in
for the real Overpass/osmnx traffic without ever making a request.
"""

from __future__ import annotations

import os
import socket as socket_module
import urllib.request
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
OSMNX_CACHE_DIR = FIXTURES_DIR / "osmnx"
SCE_CACHE_DIR = FIXTURES_DIR / "cache"

NETWORK_ERROR = "network access attempted in a test"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: allow real network access; runs against live APIs, not CI"
    )


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every form of outbound network access raise, unless opted out.

    Patches at four layers so nothing sneaks through: raw sockets, urllib,
    and both the low-level and high-level requests entry points.
    """
    if request.node.get_closest_marker("live"):
        return

    def _blocked(*args: object, **kwargs: object) -> None:
        raise RuntimeError(NETWORK_ERROR)

    try:
        import requests.adapters

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _blocked, raising=True)
    except ImportError:
        pass

    try:
        import requests

        monkeypatch.setattr(requests.Session, "request", _blocked, raising=True)
    except ImportError:
        pass

    monkeypatch.setattr(urllib.request, "urlopen", _blocked, raising=True)
    monkeypatch.setattr(socket_module.socket, "connect", _blocked, raising=True)


@pytest.fixture(autouse=True, scope="session")
def _offline_env() -> None:
    """Point sce's cache and osmnx's cache at committed, frozen fixtures."""
    OSMNX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["SCE_CACHE"] = str(SCE_CACHE_DIR)
    os.environ["SCE_OFFLINE"] = "1"

    try:
        import osmnx as ox

        ox.settings.cache_folder = str(OSMNX_CACHE_DIR)
        ox.settings.use_cache = True
    except ImportError:
        pass


@pytest.fixture
def tmp_cache(tmp_path: Path):
    """A throwaway, non-offline Cache for tests that exercise cache behaviour."""
    from sce.cache import Cache

    return Cache(root=tmp_path / "cache", offline=False)


@pytest.fixture
def tashkent_aoi():
    from sce.aoi import AOI

    return AOI.from_point(69.2401, 41.2995, 1500, name="tashkent")


@pytest.fixture
def london_aoi():
    from sce.aoi import AOI

    return AOI.from_point(-0.1276, 51.5072, 1500, name="london")


@pytest.fixture
def riyadh_aoi():
    from sce.aoi import AOI

    return AOI.from_point(46.6753, 24.7136, 1500, name="riyadh")
