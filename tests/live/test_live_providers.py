"""Tests that actually hit the network, run weekly and never in normal CI.

The README claims this tool works today against live, keyless, public
interfaces. That claim rots silently: a bucket is renamed, an API adds a
required parameter, a dataset is reorganised, and nothing in an offline suite
notices. These tests exist so the claim is machine-checked rather than
asserted, and so the weekly job goes red on the day it stops being true rather
than the day someone runs a demo.

Every test here is marked `live` and deselected by default. Run them with:

    pytest -m live

They deliberately assert loose, physical bounds rather than exact values.
The point is to catch an interface that has moved or a dataset that has been
withdrawn, not to pin numbers that legitimately drift as OpenStreetMap is
edited and climate archives are extended.
"""

from __future__ import annotations

import pytest

from sce.aoi import AOI
from sce.cache import Cache

pytestmark = pytest.mark.live

RADIUS_M = 800.0

SITES = {
    "tashkent": (69.2401, 41.2995),
    "london": (-0.1276, 51.5074),
    "riyadh": (46.6753, 24.7136),
}


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    """A cache outside the offline fixture directory, so these tests really fetch."""
    return Cache(tmp_path_factory.mktemp("live-cache"), offline=False)


def _aoi(name: str) -> AOI:
    lon, lat = SITES[name]
    return AOI.from_point(lon, lat, RADIUS_M, name=name)


# Overpass allows two concurrent slots and refuses connections beyond them. That
# is a throttle, not a broken interface, and failing on it would make the weekly
# job cry wolf until nobody reads it. Anything else -- a moved bucket, a renamed
# field, a withdrawn dataset -- must still fail loudly, which is the only reason
# this file exists.
THROTTLE_SIGNS = (
    "connection refused",
    "max retries exceeded",
    "too many requests",
    "429",
    "503",
    "504",
    "timed out",
    "temporarily unavailable",
)


def _is_throttled(message: str) -> bool:
    lowered = message.lower()
    return any(sign in lowered for sign in THROTTLE_SIGNS)


def _fetch(layer: str, name: str, cache: Cache, **kwargs):
    """Fetch a layer, skipping only when the host throttled us."""
    import sce.providers  # noqa: F401  - registers providers
    from sce.registry import REGISTRY

    aoi = _aoi(name)
    chain = REGISTRY.chain(layer, aoi)
    if kwargs.get("override"):
        chain = [p for p in chain if p.name == kwargs["override"]]
    assert chain, f"no provider is registered and available for {layer!r} at {name}"

    failures = []
    for provider in chain:
        if not provider.commercial_ok and not kwargs.get("allow_non_commercial"):
            continue
        try:
            result = provider.fetch(aoi, cache)
        except Exception as exc:
            failures.append(f"{provider.name}: {exc}")
            continue
        if result is not None and not result.is_empty:
            return result
        failures.append(f"{provider.name}: returned nothing")

    joined = " | ".join(failures)
    if _is_throttled(joined):
        pytest.skip(f"{layer} host throttled this run, not a broken interface: {joined[:200]}")
    pytest.fail(f"{layer} at {name} produced nothing: {joined}")


# --- OpenStreetMap via Overpass -------------------------------------------


@pytest.mark.parametrize("site", ["tashkent", "london"])
def test_osm_streets_still_returns_a_projected_network(site, cache):
    result = _fetch("streets", site, cache)
    assert result is not None, "no provider returned streets"
    assert len(result.gdf) > 100
    assert result.gdf.crs == _aoi(site).crs, "provider returned unprojected geometry"
    assert result.data and result.data.get("graph") is not None


def test_osm_buildings_footprints_cover_a_plausible_share_of_the_site(cache):
    """Ground coverage above 1.0 would mean footprints are being double counted;
    near zero would mean the query has stopped returning polygons."""
    import shapely

    aoi = _aoi("london")
    result = _fetch("buildings", "london", cache)
    assert result is not None
    union = shapely.union_all([shapely.make_valid(g) for g in result.gdf.geometry])
    coverage = union.area / aoi.area_m2
    assert 0.05 < coverage < 0.95, f"implausible built coverage {coverage:.3f}"


# --- Copernicus GLO-30 elevation ------------------------------------------


@pytest.mark.parametrize(
    "site,low,high",
    [("tashkent", 300, 700), ("london", -20, 120), ("riyadh", 500, 800)],
)
def test_copernicus_elevation_is_in_the_right_range(site, low, high, cache):
    """Wrong tile, wrong sign convention or a stale bucket all show up here."""
    import numpy as np

    result = _fetch("terrain", site, cache)
    assert result is not None and result.raster is not None
    arr = np.asarray(result.raster["array"], dtype=float)
    assert low < float(np.nanmean(arr)) < high


def test_terrain_raster_is_square_and_metric(cache):
    """The reprojection to a square metre grid must happen inside the provider;
    slope computed on a geographic raster is silently, invisibly wrong."""
    from pyproj import CRS

    result = _fetch("terrain", "tashkent", cache)
    tr = result.raster["transform"]
    assert abs(abs(tr.a) - abs(tr.e)) < 1e-6, "raster pixels are not square"
    assert not CRS.from_user_input(result.raster["crs"]).is_geographic


# --- ESA WorldCover --------------------------------------------------------


def test_worldcover_sees_riyadh_as_dry(cache):
    """A desert city must be dominated by built-up and bare ground. If this
    fails, the tile indexing has drifted and every land cover panel is wrong."""
    result = _fetch("landcover", "riyadh", cache)
    assert result is not None
    fractions = (result.data or {}).get("class_fractions") or {}
    dry = sum(v for k, v in fractions.items() if "Bare" in k or "Built" in k)
    assert dry > 0.8, f"Riyadh land cover looks wrong: {fractions}"


def test_worldcover_sees_london_as_built_up_with_trees(cache):
    result = _fetch("landcover", "london", cache)
    fractions = (result.data or {}).get("class_fractions") or {}
    assert fractions.get("Built-up", 0) > 0.4
    assert fractions.get("Tree cover", 0) > 0.03


# --- Open-Meteo ERA5 archive ----------------------------------------------


def test_climate_separates_a_hot_city_from_a_temperate_one(cache):
    """Riyadh must need far more cooling than London and London far more
    heating than Riyadh. A units change or a renamed field breaks this."""
    from sce.metrics.climate import climate_metrics

    riyadh = climate_metrics({"climate": _fetch("climate", "riyadh", cache)}, _aoi("riyadh"))
    london = climate_metrics({"climate": _fetch("climate", "london", cache)}, _aoi("london"))

    assert riyadh["cdd_18c"] > 10 * london["cdd_18c"]
    assert london["hdd_18c"] > 5 * riyadh["hdd_18c"]
    assert riyadh["ghi_kwh_m2_year"] > london["ghi_kwh_m2_year"]
    assert 800 < london["ghi_kwh_m2_year"] < 1600


def test_wind_rose_still_sums_to_one(cache):
    rose = (_fetch("climate", "london", cache).data or {}).get("wind_rose") or {}
    total = sum(sum(row) for row in rose["frequencies"])
    assert total == pytest.approx(1.0, abs=1e-6)


# --- planning.data.gov.uk --------------------------------------------------


def test_uk_constraints_are_returned_for_london_and_not_offered_elsewhere(cache):
    """The 'richer where richer' promise. Also guards the bbox filter bug: this
    API silently ignores a plain bbox parameter and returns national results,
    so the geometry must actually fall inside the site."""
    import sce.providers  # noqa: F401
    from sce.registry import REGISTRY

    london = _aoi("london")
    result = _fetch("constraints", "london", cache)
    assert result is not None and len(result.gdf) > 0
    assert result.gdf.geometry.intersects(london.geometry).all(), (
        "constraint geometry falls outside the requested site; the spatial filter is being ignored"
    )

    for elsewhere in ("tashkent", "riyadh"):
        assert not REGISTRY.chain("constraints", _aoi(elsewhere)), (
            f"a UK-only provider offered itself for {elsewhere}"
        )


# --- GHSL building height --------------------------------------------------


def test_ghsl_building_height_is_physically_plausible(cache):
    result = _fetch("building_height", "tashkent", cache)
    assert result is not None
    mean_height = (result.data or {}).get("mean_height_m")
    assert 1.0 < mean_height < 60.0, f"implausible mean building height {mean_height}"


# --- Overture fallback -----------------------------------------------------


@pytest.mark.slow
def test_overture_still_serves_buildings_when_osm_cannot(cache):
    """The fallback that covers Overpass rate limiting. Slow by nature: the
    public bucket's row-group statistics do not prune tightly on a bbox."""
    result = _fetch("buildings", "riyadh", cache, override="overture_buildings")
    assert result is not None and len(result.gdf) > 100
    assert result.gdf.crs == _aoi("riyadh").crs
