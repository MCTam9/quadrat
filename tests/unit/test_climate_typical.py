"""Typical year, monthly summary and the web climate contract (offline, synthetic)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np

from sce.climate import climate_summary, monthly_summary, to_local_standard, typical_year


def synthetic_hourly(years=(2019, 2020, 2021), warm_year=None, offset_h=0):
    """Hourly UTC series built from sinusoids; `warm_year` gets +4 C."""
    t0 = np.datetime64(f"{years[0]}-01-01T00:00", "m")
    t1 = np.datetime64(f"{years[-1] + 1}-01-01T00:00", "m")
    time = np.arange(t0, t1, np.timedelta64(60, "m"))
    doy = (time.astype("datetime64[D]") - time.astype("datetime64[Y]").astype("datetime64[D]")).astype(float)
    hod = ((time - time.astype("datetime64[D]").astype("datetime64[m]")) // np.timedelta64(1, "h")).astype(
        float
    )
    yr = time.astype("datetime64[Y]").astype(int) + 1970
    temp = 10 - 8 * np.cos(2 * np.pi * (doy - 10) / 365) - 4 * np.cos(2 * np.pi * (hod - 3) / 24)
    if warm_year:
        temp = temp + np.where(yr == warm_year, 4.0, 0.0)
    sun = np.clip(np.sin(np.pi * (hod - 6) / 12), 0, None)
    season = 0.6 + 0.4 * np.sin(2 * np.pi * (doy - 80) / 365)
    ghi = 700 * sun * season
    n = len(time)
    return {
        "time": time,
        "temperature_c": temp,
        "dew_point_c": temp - 4,
        "relative_humidity_pct": np.full(n, 75.0),
        "pressure_pa": np.full(n, 101000.0),
        "ghi_wm2": ghi,
        "dni_wm2": ghi * 0.6,
        "dhi_wm2": ghi * 0.4,
        "wind_speed_ms": 4 + np.sin(2 * np.pi * doy / 365),
        "wind_direction_deg": np.full(n, 225.0),
        "cloud_cover_pct": np.full(n, 50.0),
        "precipitation_mm": np.full(n, 0.1),
    }


def test_typical_year_shape_and_months():
    ty = typical_year(synthetic_hourly(), 0.0)
    assert len(ty["hourly"]) == 11
    assert "time" not in ty["hourly"]
    for arr in ty["hourly"].values():
        assert arr.shape == (8760,)
    assert len(ty["months_from_years"]) == 12
    assert set(ty["months_from_years"]) <= {2019, 2020, 2021}
    assert ty["method"]


def test_average_year_is_chosen():
    # 2020 is +4 C warm, the other years are identical; the odd one out must lose.
    # Four years, because timestamps are hour-ending: the last December of the
    # record is one hour short, and with only two candidates the FS distances
    # to their pooled CDF are symmetric (a tie).
    ty = typical_year(synthetic_hourly(years=(2019, 2020, 2021, 2022), warm_year=2020), 0.0)
    assert 2020 not in ty["months_from_years"]


def test_middle_year_chosen_when_others_straddle_it():
    h = synthetic_hourly(years=(2019, 2020, 2021))
    yr = h["time"].astype("datetime64[Y]").astype(int) + 1970
    h["temperature_c"] = h["temperature_c"] + np.select([yr == 2019, yr == 2021], [-3.0, 3.0], 0.0)
    h["dew_point_c"] = h["temperature_c"] - 4
    ty = typical_year(h, 0.0)
    assert ty["months_from_years"] == [2020] * 12


def test_nan_gaps_filled():
    h = synthetic_hourly()
    h["temperature_c"][5000:5010] = np.nan
    ty = typical_year(h, 0.0)
    assert np.isfinite(ty["hourly"]["temperature_c"]).all()


def test_local_shift_rounds_fractional_offsets():
    h = synthetic_hourly()
    shifted = to_local_standard(h, 5.5)
    # +6 h (5.5 rounded) local, -1 h because Open-Meteo stamps are hour-ending.
    assert (shifted["time"][0] - h["time"][0]) == np.timedelta64(5, "h")


def test_monthly_summary_sane():
    rows = monthly_summary(synthetic_hourly(), 0.0)
    assert [r["month"] for r in rows] == list(range(1, 13))
    jan, jul = rows[0], rows[6]
    assert jul["temp_mean_c"] > jan["temp_mean_c"] + 8
    for r in rows:
        assert r["temp_record_min_c"] <= r["temp_mean_daily_min_c"] <= r["temp_mean_c"]
        assert r["temp_mean_c"] <= r["temp_mean_daily_max_c"] <= r["temp_record_max_c"]
        assert r["rh_mean_pct"] == 75.0
    # 0.1 mm every hour: January is 31*24*0.1 per year.
    assert abs(jan["precip_mm"] - 74.4) < 0.5
    assert jul["ghi_kwh_m2"] > jan["ghi_kwh_m2"]


def _layer(hourly):
    src = SimpleNamespace(name="Open-Meteo ERA5", licence="CC BY 4.0", note="regional")
    data = {
        "hourly": hourly,
        "timezone": {"name": "Europe/London", "standard_offset_h": 0.0, "approximate": False},
        "elevation_m": 25.0,
        "grid_point_lonlat": [-0.1, 51.5],
        "period": "2019-01-01 to 2021-12-31",
    }
    return SimpleNamespace(data=data, sources=[src])


def test_climate_summary_contract_and_json_safe():
    h = synthetic_hourly()
    h["pressure_pa"][100] = np.nan  # NaN must not leak to JSON
    s = climate_summary(_layer(h))
    assert set(s) == {"source", "timezone", "typical_year", "monthly", "annual"}
    assert set(s["source"]) == {"name", "period", "grid_point_lonlat", "elevation_m", "licence", "note"}
    assert set(s["annual"]) == {"hdd_18c", "cdd_18c", "ghi_kwh_m2", "mean_temp_c", "precip_mm"}
    assert len(s["monthly"]) == 12
    hourly = s["typical_year"]["hourly"]
    assert len(hourly) == 11
    assert all(isinstance(v, list) and len(v) == 8760 for v in hourly.values())
    json.dumps(s, allow_nan=False)
    assert s["annual"]["hdd_18c"] > 0
    assert abs(s["annual"]["precip_mm"] - 876.6) < 2
