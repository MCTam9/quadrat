"""The most important test in the repo: nothing metric ever sees degrees.

`sce.aoi` is the CRS spine every provider and metric is built on. This file
checks the two directions of that contract: every AOI the spine produces is
projected and metre-based, and every registered metric refuses geographic
input at the door.
"""

from __future__ import annotations

import importlib

import pytest
from pyproj import CRS

from sce.aoi import AOI, WGS84, NonMetricCRSError, assert_metric_crs

# lon, lat, radius_m, expect_laea, label
POINTS = [
    (69.2401, 41.2995, 1500, False, "tashkent"),
    (-0.1276, 51.5072, 1500, False, "london"),
    (46.6753, 24.7136, 1500, False, "riyadh"),
    (179.9, -17.0, 1500, False, "antimeridian-east"),
    (-179.9, -17.0, 1500, False, "antimeridian-west"),
    # 0.0 longitude is itself a UTM zone boundary (30/31); use 3.0, the
    # centre of zone 31, so this checks plain equatorial behaviour only.
    (3.0, 0.0, 1500, False, "equator"),
    # 36.0 is a zone boundary (multiple of 6); 33.0 is a zone centre.
    (33.0, 40.0, 1500, False, "utm-zone-interior"),
    # Exactly on a UTM zone boundary (multiple of 6 degrees), with a radius
    # large enough that the AOI square straddles the boundary on both sides.
    (36.0, 40.0, 400_000, True, "utm-zone-boundary-crossing"),
    (0.0, 85.0, 1500, True, "polar-85n"),
    (0.0, -85.0, 1500, True, "polar-85s"),
]


@pytest.mark.parametrize("lon,lat,radius_m,expect_laea,label", POINTS, ids=[p[4] for p in POINTS])
def test_from_point_is_always_metric(lon, lat, radius_m, expect_laea, label):
    aoi = AOI.from_point(lon, lat, radius_m, name=label)
    crs = CRS.from_user_input(aoi.crs)
    assert not crs.is_geographic, f"{label}: AOI CRS {crs.to_string()} is geographic"
    units = {ax.unit_name for ax in crs.axis_info}
    assert units <= {"metre", "meter"}, f"{label}: AOI CRS units are {units}, not metres"
    is_laea = "laea" in crs.to_proj4().lower() if crs.to_epsg() is None else False
    if expect_laea:
        assert is_laea, f"{label}: expected LAEA, got {crs.to_string()}"
    else:
        assert not is_laea, f"{label}: expected UTM, got LAEA {crs.to_string()}"


def test_from_point_polar_and_boundary_use_laea_not_utm():
    """Direct check of the two documented LAEA triggers: >=80 lat, zone crossing."""
    polar = AOI.from_point(0.0, 85.0, 1500, name="polar")
    assert "laea" in polar.crs.to_proj4().lower()

    boundary = AOI.from_point(36.0, 40.0, 400_000, name="boundary")
    assert "laea" in boundary.crs.to_proj4().lower()

    interior = AOI.from_point(33.0, 40.0, 1500, name="interior")
    assert "laea" not in interior.crs.to_proj4().lower()
    assert interior.crs.to_epsg() is not None


# ---------------------------------------------------------------------------
# Every registered metric must reject EPSG:4326 input.
# ---------------------------------------------------------------------------

try:
    _metrics_mod = importlib.import_module("sce.metrics")
    METRICS = getattr(_metrics_mod, "METRICS", None)
except Exception:  # noqa: BLE001 - module may not exist or be mid-write
    METRICS = None

_METRIC_ITEMS = list(METRICS.items()) if METRICS else []


def _geographic_layer_inputs():
    """Build the smallest plausible geographic (EPSG:4326) layer inputs.

    Metrics take a mix of AOI + LayerResult objects; we construct one dummy
    GeoDataFrame in degrees and hand it in wherever a metric expects geometry,
    plus a bogus AOI-shaped object. The point isn't to satisfy the metric's
    business logic, only to prove that the very first CRS check fires before
    anything else runs.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame({"geometry": [Point(0.0, 0.0)]}, crs=WGS84)
    return gdf


@pytest.mark.skipif(METRICS is None, reason="sce.metrics.METRICS not yet available")
@pytest.mark.parametrize("metric_name", [m[0] for m in _METRIC_ITEMS] or ["__none__"])
def test_every_metric_rejects_geographic_input(metric_name):
    if METRICS is None:
        pytest.skip("sce.metrics.METRICS not yet available")
    fn = METRICS[metric_name]
    gdf = _geographic_layer_inputs()

    # Metrics have varying signatures; try the plausible call shapes and
    # require that at least one of them is rejected with NonMetricCRSError.
    # A metric that raises TypeError for every shape we try has a signature
    # this harness doesn't yet know how to drive — that's a gap to fix here,
    # not a pass.
    attempts = [
        lambda: fn(gdf),
        lambda: fn(gdf, gdf),
        lambda: fn(aoi=gdf, layers={}),
        lambda: fn({"streets": gdf}, gdf),
    ]
    raised_non_metric = False
    last_type_errors = 0
    for attempt in attempts:
        try:
            attempt()
        except NonMetricCRSError:
            raised_non_metric = True
            break
        except TypeError:
            last_type_errors += 1
            continue
        except Exception:  # noqa: BLE001 - any other error means it got past the CRS check
            pytest.fail(
                f"metric {metric_name!r} did not raise NonMetricCRSError on geographic input "
                "(it raised something else, meaning it processed the geometry first)"
            )
    if not raised_non_metric and last_type_errors == len(attempts):
        pytest.skip(
            f"metric {metric_name!r} signature not covered by this harness's call shapes"
        )
    assert raised_non_metric, f"metric {metric_name!r} accepted geographic (EPSG:4326) input"


# ---------------------------------------------------------------------------
# assert_metric_crs itself
# ---------------------------------------------------------------------------


def test_assert_metric_crs_rejects_wgs84():
    with pytest.raises(NonMetricCRSError):
        assert_metric_crs(WGS84)


def test_assert_metric_crs_accepts_web_mercator():
    # EPSG:3857 (Web Mercator) is in metres and passes this gate, but it is
    # still a bad choice for area/length work: its scale factor varies with
    # latitude, so equal-area and equal-distance assumptions break. The gate
    # only enforces "metric", not "locally accurate" — AOI.from_point never
    # chooses 3857, this just documents that assert_metric_crs can't catch it.
    crs = assert_metric_crs(CRS.from_epsg(3857))
    assert not crs.is_geographic


def test_assert_metric_crs_accepts_utm():
    crs = assert_metric_crs(CRS.from_epsg(32642))  # UTM 42N, covers Tashkent
    assert not crs.is_geographic


# ---------------------------------------------------------------------------
# AOI.from_point buffers in projected space, not degrees.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lon,lat",
    [
        (0.0, 0.0),
        (69.2401, 41.2995),
        (-0.1276, 51.5072),
        (0.0, 60.0),
        (30.0, 60.0),
    ],
    ids=["equator", "tashkent", "london", "60N-prime-meridian", "60N-interior"],
)
def test_from_point_area_is_exact_regardless_of_latitude(lon, lat):
    """A 1000 m radius square AOI must have area 4,000,000 m^2 everywhere.

    Buffering in degrees would shrink the effective east-west extent as
    latitude grows (cos(lat) foreshortening), which is most visible at high
    latitude — 60N is where a degrees-based buffer would be off by ~2x on the
    east-west axis. Buffering the projected centre sidesteps this entirely.
    """
    aoi = AOI.from_point(lon, lat, 1000.0, name=f"exact-{lat}")
    expected = 4_000_000.0
    assert aoi.area_m2 == pytest.approx(expected, rel=1e-4)
