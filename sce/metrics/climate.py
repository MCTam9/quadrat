"""Climate metrics: pass-through and tidy of the provider's ERA5-derived data.

This module does no geometry of its own beyond the AOI centroid used for the
grid-offset honesty check, so `assert_metric_crs` is called against the AOI's
own CRS — the one piece of geometry every metric touches regardless of what
providers returned.
"""

from __future__ import annotations

import math
from typing import Any

from pyproj import Transformer

from ..aoi import AOI, WGS84, assert_metric_crs
from ..types import LayerResult

REQUIRED_KEYS = (
    "hdd_18c",
    "cdd_18c",
    "ghi_kwh_m2_year",
    "mean_temp_c",
    "prevailing_wind_direction_deg",
    "prevailing_wind_frequency",
)


def _first(data: dict[str, Any], *names: str) -> Any:
    """Read the first key present.

    The provider and this metric are separate modules that can be edited apart,
    so the metric accepts either spelling rather than silently returning None
    and printing a dash on the sheet. `test_climate_metric_reads_provider_keys`
    pins the pair together.
    """
    for name in names:
        if data.get(name) is not None:
            return data[name]
    return None


def _prevailing_wind(rose: Any) -> tuple[float | None, float | None]:
    """The direction bin carrying the most hours, and the share it carries.

    Derived here rather than in the provider because it is a reading of the
    rose, not a measurement: the rose is the data, this is the sentence you put
    beside the orientation plot.
    """
    if not isinstance(rose, dict):
        return None, None
    freqs = rose.get("frequencies")
    if not freqs:
        return None, None
    totals = [sum(row) if isinstance(row, (list, tuple)) else float(row) for row in freqs]
    if not totals or sum(totals) <= 0:
        return None, None
    idx = max(range(len(totals)), key=totals.__getitem__)
    bin_width = 360.0 / len(totals)
    return idx * bin_width, totals[idx] / sum(totals)


def climate_metrics(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    assert_metric_crs(aoi.crs, where="climate_metrics")

    climate = layers["climate"]
    data = climate.data or {}

    result: dict[str, Any] = {}
    result["hdd_18c"] = _first(data, "hdd_18c", "hdd_18c_annual_mean")
    result["cdd_18c"] = _first(data, "cdd_18c", "cdd_18c_annual_mean")
    result["ghi_kwh_m2_year"] = _first(data, "ghi_kwh_m2_year", "ghi_kwh_m2_annual")
    result["mean_temp_c"] = _first(data, "mean_temp_c", "mean_temperature_c")

    direction, frequency = _prevailing_wind(data.get("wind_rose"))
    result["prevailing_wind_direction_deg"] = direction
    result["prevailing_wind_frequency"] = frequency

    grid_lonlat = data.get("grid_point_lonlat")
    if grid_lonlat is not None:
        lon, lat = aoi.centroid_lonlat
        tf = Transformer.from_crs(WGS84, aoi.crs, always_xy=True)
        cx, cy = tf.transform(lon, lat)
        gx, gy = tf.transform(grid_lonlat[0], grid_lonlat[1])
        offset_m = math.hypot(gx - cx, gy - cy)
        result["climate_grid_offset_km"] = offset_m / 1000.0
    else:
        result["climate_grid_offset_km"] = None

    missing = [k for k in REQUIRED_KEYS if result.get(k) is None]
    if missing:
        result["climate_incomplete_fields"] = missing

    return result


climate_metrics.REQUIRES = ("climate",)
# This metric reads scalars the climate provider already computed and never
# touches geometry, so it has no metric-CRS door to guard. The CRS contract test
# reads this flag rather than carrying a hard-coded exemption of its own.
climate_metrics.TOUCHES_GEOMETRY = False
