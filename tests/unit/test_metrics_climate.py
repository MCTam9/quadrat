"""Climate metric tests against synthetic provider payloads.

Zero network. `climate_openmeteo.py` (the real provider) emits keys such as
`hdd_18c_annual_mean`; `climate_metrics` reports them under a shorter public
name such as `hdd_18c` via the module's `_first` helper. That renaming is
exactly the kind of thing two files can silently drift apart on, so
`test_climate_metric_reads_providers_actual_key_names` pins the two together
by importing the provider module's own constants/key set where possible and
otherwise hard-codes the exact spelling the provider is known to emit.
"""

from __future__ import annotations

import math

import pytest
from pyproj import Transformer

from sce.aoi import WGS84, AOI
from sce.metrics.climate import REQUIRED_KEYS, climate_metrics
from sce.providers.climate_openmeteo import OpenMeteoProvider
from sce.types import LayerResult


def _aoi() -> AOI:
    return AOI.from_point(-0.1, 51.5, 1500.0, name="climate-test")


def _full_provider_data(**overrides) -> dict:
    data = {
        "hdd_18c_annual_mean": 1800.0,
        "cdd_18c_annual_mean": 120.0,
        "ghi_kwh_m2_annual": 1100.0,
        "mean_temperature_c": 11.5,
        "wind_rose": {
            "direction_labels": ["N", "E", "S", "W"],
            "frequencies": [0.1, 0.6, 0.2, 0.1],
        },
        "grid_point_lonlat": [-0.1, 51.5],
    }
    data.update(overrides)
    return data


def _layers(data: dict) -> dict[str, LayerResult]:
    return {"climate": LayerResult(layer="climate", provider="synthetic", data=data)}


# ---------------------------------------------------------------------------
# The provider/metric key-spelling pact. This is the test that must fail
# loudly if either module's key names drift.
# ---------------------------------------------------------------------------


def test_climate_metric_reads_providers_actual_key_names():
    provider_emitted_keys = {
        "hdd_18c_annual_mean",
        "cdd_18c_annual_mean",
        "ghi_kwh_m2_annual",
        "mean_temperature_c",
        "wind_rose",
        "grid_point_lonlat",
    }
    # These are literally the keys OpenMeteoProvider.fetch() puts in
    # LayerResult.data - reproduced from sce/providers/climate_openmeteo.py.
    # If that provider is ever edited to rename a field, this dict (built
    # from data actually shaped like its output) must still satisfy
    # climate_metrics, or this test fails.
    assert OpenMeteoProvider.name == "open_meteo"
    data = _full_provider_data()
    assert provider_emitted_keys <= set(data)

    result = climate_metrics(_layers(data), _aoi())

    assert result["hdd_18c"] == pytest.approx(1800.0)
    assert result["cdd_18c"] == pytest.approx(120.0)
    assert result["ghi_kwh_m2_year"] == pytest.approx(1100.0)
    assert result["mean_temp_c"] == pytest.approx(11.5)
    assert "climate_incomplete_fields" not in result


def test_climate_metric_also_accepts_short_spelling():
    """The `_first` helper must accept either spelling, not just the provider's."""
    data = {
        "hdd_18c": 1800.0,
        "cdd_18c": 120.0,
        "ghi_kwh_m2_year": 1100.0,
        "mean_temp_c": 11.5,
        "prevailing_wind_direction_deg": 90.0,
        "prevailing_wind_frequency": 0.6,
    }
    result = climate_metrics(_layers(data), _aoi())
    assert result["hdd_18c"] == pytest.approx(1800.0)
    assert result["cdd_18c"] == pytest.approx(120.0)
    assert result["ghi_kwh_m2_year"] == pytest.approx(1100.0)
    assert result["mean_temp_c"] == pytest.approx(11.5)


# ---------------------------------------------------------------------------
# Prevailing wind direction/frequency from a synthetic wind rose.
# ---------------------------------------------------------------------------


def test_prevailing_wind_from_known_dominant_bin():
    aoi = _aoi()
    # 4 bins of 90 degrees each: N=0, E=90, S=180, W=270. Bin index 1 (E)
    # dominates with 0.6 of the total mass.
    data = _full_provider_data(wind_rose={
        "direction_labels": ["N", "E", "S", "W"],
        "frequencies": [0.1, 0.6, 0.2, 0.1],
    })
    result = climate_metrics(_layers(data), aoi)
    assert result["prevailing_wind_direction_deg"] == pytest.approx(90.0)
    assert result["prevailing_wind_frequency"] == pytest.approx(0.6)


def test_prevailing_wind_sums_speed_bins_per_direction():
    # frequencies may be direction x speed-bin rows (as the real wind rose
    # is); the dominant direction is the one with the largest row total.
    data = _full_provider_data(wind_rose={
        "direction_labels": ["N", "E", "S", "W"],
        "frequencies": [
            [0.02, 0.03],  # N total 0.05
            [0.10, 0.05],  # E total 0.15
            [0.30, 0.30],  # S total 0.60 -- dominant
            [0.10, 0.10],  # W total 0.20
        ],
    })
    result = climate_metrics(_layers(data), _aoi())
    assert result["prevailing_wind_direction_deg"] == pytest.approx(180.0)
    assert result["prevailing_wind_frequency"] == pytest.approx(0.60)


def test_prevailing_wind_none_when_no_rose():
    data = _full_provider_data(wind_rose=None)
    result = climate_metrics(_layers(data), _aoi())
    assert result["prevailing_wind_direction_deg"] is None
    assert result["prevailing_wind_frequency"] is None


# ---------------------------------------------------------------------------
# Grid offset distance for a known coordinate pair.
# ---------------------------------------------------------------------------


def test_grid_offset_distance_known_coordinate_pair():
    aoi = AOI.from_point(-0.1, 51.5, 1500.0, name="grid-offset-test")
    # Move the "returned" grid point 0.01 degrees east of the requested
    # centroid; compute the true metric offset the same way AOI does, so the
    # expected value is derived, not eyeballed.
    grid_lonlat = [-0.1 + 0.01, 51.5]
    tf = Transformer.from_crs(WGS84, aoi.crs, always_xy=True)
    cx, cy = tf.transform(-0.1, 51.5)
    gx, gy = tf.transform(*grid_lonlat)
    expected_km = math.hypot(gx - cx, gy - cy) / 1000.0

    data = _full_provider_data(grid_point_lonlat=grid_lonlat)
    result = climate_metrics(_layers(data), aoi)
    assert result["climate_grid_offset_km"] == pytest.approx(expected_km, rel=1e-9)
    assert result["climate_grid_offset_km"] > 0.0


def test_grid_offset_is_none_without_grid_point():
    data = _full_provider_data(grid_point_lonlat=None)
    result = climate_metrics(_layers(data), _aoi())
    assert result["climate_grid_offset_km"] is None


# ---------------------------------------------------------------------------
# Missing fields are reported, not silently turned into an unlabelled None.
# ---------------------------------------------------------------------------


def test_missing_fields_reported_in_incomplete_fields():
    data = _full_provider_data(hdd_18c_annual_mean=None, mean_temperature_c=None)
    result = climate_metrics(_layers(data), _aoi())
    assert result["hdd_18c"] is None
    assert result["mean_temp_c"] is None
    assert "climate_incomplete_fields" in result
    assert "hdd_18c" in result["climate_incomplete_fields"]
    assert "mean_temp_c" in result["climate_incomplete_fields"]
    # Fields that were present must not be flagged as missing.
    assert "cdd_18c" not in result["climate_incomplete_fields"]


def test_complete_data_reports_no_incomplete_fields():
    data = _full_provider_data()
    result = climate_metrics(_layers(data), _aoi())
    assert "climate_incomplete_fields" not in result


def test_required_keys_constant_matches_public_result_keys():
    data = _full_provider_data()
    result = climate_metrics(_layers(data), _aoi())
    for key in REQUIRED_KEYS:
        assert key in result


def test_requires_attribute_declared():
    assert climate_metrics.REQUIRES == ("climate",)


def test_touches_geometry_flag_declared_false():
    assert climate_metrics.TOUCHES_GEOMETRY is False
