"""The most important test in the repo: nothing metric ever sees degrees.

`sce.aoi` is the CRS spine every provider and metric is built on. This file
checks the two directions of that contract: every AOI the spine produces is
projected and metre-based, and every registered metric refuses geographic
input at the door.
"""

from __future__ import annotations

import importlib

import pytest
from affine import Affine
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


def _geographic_layers(required: tuple[str, ...]):
    """Build a LayerResult for each required layer, all in EPSG:4326.

    This is the exact shape a metric is called with in production, only with
    degrees where metres belong. A metric that gets past this has an area or a
    length computed in square degrees somewhere inside it.
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import LineString, Polygon

    from sce.types import LayerResult

    shapes = {
        "streets": [LineString([(0.0, 0.0), (0.01, 0.0)]), LineString([(0.0, 0.0), (0.0, 0.01)])],
        "buildings": [Polygon([(0, 0), (0.001, 0), (0.001, 0.001), (0, 0.001)])],
        "landuse": [Polygon([(0, 0), (0.002, 0), (0.002, 0.002), (0, 0.002)])],
        "amenities": [LineString([(0.0, 0.0), (0.001, 0.0)]).centroid],
    }
    layers: dict[str, LayerResult] = {}
    for layer in required:
        if layer == "terrain":
            layers[layer] = LayerResult(
                layer="terrain",
                provider="test",
                raster={
                    "array": np.zeros((8, 8), dtype=float),
                    "transform": Affine(0.0003, 0.0, 0.0, 0.0, -0.0003, 0.0),
                    "crs": CRS.from_epsg(4326),
                    "nodata": None,
                    "res": (0.0003, 0.0003),
                },
            )
            continue
        if layer == "climate":
            layers[layer] = LayerResult(layer="climate", provider="test", data={})
            continue
        geoms = shapes.get(layer, shapes["buildings"])
        gdf = gpd.GeoDataFrame({"geometry": geoms}, crs=WGS84)
        if layer == "buildings":
            gdf["height_m"] = [12.0] * len(geoms)
            gdf["height_source"] = ["height"] * len(geoms)
        if layer in ("landuse", "amenities"):
            gdf["class"] = ["residential"] * len(geoms)
            gdf["category"] = ["transport"] * len(geoms)
        layers[layer] = LayerResult(layer=layer, provider="test", gdf=gdf)
    return layers


@pytest.mark.skipif(METRICS is None, reason="sce.metrics.METRICS not yet available")
@pytest.mark.parametrize("metric_name", sorted(METRICS or {}) or ["__none__"])
def test_every_metric_rejects_geographic_input(metric_name):
    """Every registered metric must refuse degrees, at the door, before anything
    else runs.

    Metrics are called exactly as `compute_all` calls them: `fn(layers, aoi)`.
    The AOI is real and projected; only the layer geometry is geographic, which
    is the realistic failure mode - a provider that forgot to reproject.
    """
    if METRICS is None:
        pytest.skip("sce.metrics.METRICS not yet available")
    fn = METRICS[metric_name]
    required = getattr(fn, "REQUIRES", ())
    if not required:
        pytest.skip(f"metric {metric_name!r} declares no required layers to poison")
    if not getattr(fn, "TOUCHES_GEOMETRY", True):
        pytest.skip(f"metric {metric_name!r} declares it touches no geometry")

    aoi = AOI.from_point(3.0, 40.0, 1000.0, name="crs-contract")
    layers = _geographic_layers(required)

    with pytest.raises(NonMetricCRSError):
        fn(layers, aoi)


@pytest.mark.skipif(METRICS is None, reason="sce.metrics.METRICS not yet available")
def test_every_metric_declares_its_required_layers():
    """`compute_all` skips on REQUIRES, so a metric without it silently runs on
    absent data and returns nonsense instead of nothing."""
    if METRICS is None:
        pytest.skip("sce.metrics.METRICS not yet available")
    missing = [n for n, fn in METRICS.items() if not hasattr(fn, "REQUIRES")]
    assert not missing, f"metrics without a REQUIRES tuple: {missing}"


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
