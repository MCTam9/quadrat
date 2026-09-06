"""Terrain metrics against analytically known slopes.

A tilted plane at exactly 1:20 has a known, constant slope everywhere
(`arctan(1/20) = 2.8624 degrees`) — `numpy.gradient` on a truly linear surface
reproduces the analytic derivative exactly, including at the array edges.
"""

from __future__ import annotations

import numpy as np
import pytest

from sce.aoi import AOI, NonMetricCRSError
from sce.metrics.terrain import BUILDABLE_SLOPE_DEG, terrain_metrics
from sce.types import LayerResult

EXPECTED_1_20_DEG = np.degrees(np.arctan(1.0 / 20.0))


def _aoi() -> AOI:
    return AOI.from_point(0.0, 51.0, 50.0, name="terrain")


def _plane_raster(gradient_x: float, aoi_crs, n: int = 20, res: float = 1.0):
    xs = np.arange(n) * res
    array = np.tile(xs * gradient_x, (n, 1))
    return {"array": array, "crs": aoi_crs, "nodata": None, "res": (res, res)}


def test_flat_plane_has_zero_slope():
    aoi = _aoi()
    raster = _plane_raster(0.0, aoi.crs)
    layers = {"terrain": LayerResult(layer="terrain", provider="synthetic", raster=raster)}
    result = terrain_metrics(layers, aoi)
    assert result["slope_mean_deg"] == pytest.approx(0.0, abs=1e-9)
    assert result["buildable_fraction_under_1_20"] == pytest.approx(1.0)
    assert result["terrain_model"] == "DSM"


def test_tilted_plane_at_exactly_1_in_20():
    aoi = _aoi()
    raster = _plane_raster(1.0 / 20.0, aoi.crs)
    layers = {"terrain": LayerResult(layer="terrain", provider="synthetic", raster=raster)}
    result = terrain_metrics(layers, aoi)
    assert result["slope_mean_deg"] == pytest.approx(EXPECTED_1_20_DEG, abs=1e-6)
    assert result["slope_mean_deg"] == pytest.approx(2.8624, abs=1e-3)
    assert result["buildable_fraction_under_1_20"] == pytest.approx(1.0)
    assert result["dominant_aspect"] == "W"


def test_steep_plane_is_not_buildable():
    aoi = _aoi()
    raster = _plane_raster(1.0 / 5.0, aoi.crs)
    layers = {"terrain": LayerResult(layer="terrain", provider="synthetic", raster=raster)}
    result = terrain_metrics(layers, aoi)
    assert result["slope_mean_deg"] > BUILDABLE_SLOPE_DEG
    assert result["buildable_fraction_under_1_20"] == pytest.approx(0.0)


def test_elevation_summary_stats():
    aoi = _aoi()
    raster = _plane_raster(1.0 / 20.0, aoi.crs, n=20, res=1.0)
    layers = {"terrain": LayerResult(layer="terrain", provider="synthetic", raster=raster)}
    result = terrain_metrics(layers, aoi)
    assert result["elevation_min_m"] == pytest.approx(0.0)
    assert result["elevation_max_m"] == pytest.approx(19.0 / 20.0)
    assert result["elevation_range_m"] == pytest.approx(19.0 / 20.0)


def test_geographic_crs_rejected():
    raster = _plane_raster(0.0, "EPSG:4326")
    aoi = _aoi()
    layers = {"terrain": LayerResult(layer="terrain", provider="synthetic", raster=raster)}
    with pytest.raises(NonMetricCRSError):
        terrain_metrics(layers, aoi)


def test_requires_attribute_declared():
    assert terrain_metrics.REQUIRES == ("terrain",)
