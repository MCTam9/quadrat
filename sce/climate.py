"""Climate post-processing: typical year, monthly summaries and the web contract.

Everything here works on the `hourly` dict held in `layers["climate"].data`
(UTC, equally spaced hourly numpy arrays, see providers/climate_openmeteo.py).
Nothing here touches the network.

Times are shifted to local *standard* time (no daylight saving), the convention
of EPW files and solar geometry. Index 0 of a typical year is 1 January
00:00-01:00 local standard time.
"""

from __future__ import annotations

import math
from calendar import monthrange

import numpy as np
import pandas as pd

HDD_CDD_BASE_C = 18.0
HOURS_PER_YEAR = 8760
_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # no Feb 29
_BLEND_HOURS = 6
_MAX_NAN_FRACTION = 0.10

# TMY2 / Sandia weights (twentieths) on daily indices. Order matches _daily_indices.
_WEIGHTS = {
    "t_max": 1,
    "t_min": 1,
    "t_mean": 2,
    "td_max": 1,
    "td_min": 1,
    "td_mean": 2,
    "w_max": 1,
    "w_mean": 1,
    "ghi": 5,
    "dni": 5,
}
_FS_KEYS = ("temperature_c", "dew_point_c", "wind_speed_ms", "ghi_wm2", "dni_wm2")
_BLEND_KEYS = ("temperature_c", "dew_point_c", "relative_humidity_pct", "pressure_pa")
_OUT_KEYS = (
    "temperature_c",
    "dew_point_c",
    "relative_humidity_pct",
    "pressure_pa",
    "ghi_wm2",
    "dni_wm2",
    "dhi_wm2",
    "wind_speed_ms",
    "wind_direction_deg",
    "cloud_cover_pct",
    "precipitation_mm",
)
_METHOD = (
    "Typical Meteorological Year by month: Finkelstein-Schafer statistic over complete "
    "calendar months of the record, TMY2/Sandia weights (dry bulb 4/20, dew point 4/20, "
    "wind 2/20, GHI 5/20, DNI 5/20), the single best-scoring year per month, 6-hour linear "
    "blends across month joins for temperature, dew point, humidity and pressure. No "
    "persistence screening; 29 February dropped."
)


def to_local_standard(hourly: dict, standard_offset_h: float) -> dict:
    """Return `hourly` with `time` shifted from UTC to local standard time.

    A fractional offset (e.g. India +5.5) is rounded to the nearest whole hour,
    because the whole pipeline works on an hourly grid. The data arrays are not
    copied or changed; only `time` is replaced.

    The returned `time` is the START of the hour each value describes. Open-Meteo
    stamps radiation as the mean of the preceding hour, and EPW rows are
    hour-ending (hour 1 = 00:00-01:00), so a value stamped T belongs to the
    interval [T-1h, T): one hour is subtracted. Without this, solar data sits an
    hour early and every Ladybug radiation study is skewed towards morning.
    """
    shift = round(standard_offset_h)
    out = dict(hourly)
    out["time"] = (
        np.asarray(hourly["time"], dtype="datetime64[m]")
        + np.timedelta64(shift, "h")
        - np.timedelta64(1, "h")
    )
    return out


def _calendar(time: np.ndarray):
    t = np.asarray(time, dtype="datetime64[m]")
    year = t.astype("datetime64[Y]").astype(int) + 1970
    month = t.astype("datetime64[M]").astype(int) % 12 + 1
    day = t.astype("datetime64[D]")
    hour = ((t - day.astype("datetime64[m]")) // np.timedelta64(1, "h")).astype(int)
    return year, month, day, hour


def _fill_gaps(x: np.ndarray, circular: bool = False, zero: bool = False) -> np.ndarray:
    """Fill NaN by linear interpolation (circular for angles, zero for precipitation)."""
    x = np.asarray(x, dtype=float)
    bad = ~np.isfinite(x)
    if not bad.any():
        return x
    if zero:
        return np.where(bad, 0.0, x)
    if bad.all():
        return x
    idx = np.arange(len(x))
    if circular:
        rad = np.deg2rad(np.where(bad, 0.0, x))
        s = np.interp(idx, idx[~bad], np.sin(rad)[~bad])
        c = np.interp(idx, idx[~bad], np.cos(rad)[~bad])
        return np.mod(np.rad2deg(np.arctan2(s, c)), 360.0)
    return np.interp(idx, idx[~bad], x[~bad])


def _cdf_at(values: np.ndarray, sorted_ref: np.ndarray, cdf_ref: np.ndarray) -> np.ndarray:
    return np.interp(values, sorted_ref, cdf_ref)


def _fs(year_vals: np.ndarray, long_sorted: np.ndarray, long_cdf: np.ndarray) -> float:
    ys = np.sort(year_vals)
    n = len(ys)
    year_cdf = (np.arange(1, n + 1) - 0.5) / n
    return float(np.mean(np.abs(_cdf_at(ys, long_sorted, long_cdf) - year_cdf)))


def _daily_indices(h: dict, sl: slice) -> dict[str, np.ndarray]:
    """Ten daily indices for one (year, month) slice of whole days."""
    t = h["temperature_c"][sl].reshape(-1, 24)
    td = h["dew_point_c"][sl].reshape(-1, 24)
    w = h["wind_speed_ms"][sl].reshape(-1, 24)
    return {
        "t_max": t.max(1),
        "t_min": t.min(1),
        "t_mean": t.mean(1),
        "td_max": td.max(1),
        "td_min": td.min(1),
        "td_mean": td.mean(1),
        "w_max": w.max(1),
        "w_mean": w.mean(1),
        "ghi": h["ghi_wm2"][sl].reshape(-1, 24).sum(1),
        "dni": h["dni_wm2"][sl].reshape(-1, 24).sum(1),
    }


def typical_year(hourly: dict, standard_offset_h: float) -> dict:
    """Pick a typical month from each calendar month of the record and join them.

    Returns {"hourly": {key: ndarray(8760)}, "months_from_years": [12 ints],
    "method": str}. Raises ValueError when a calendar month has no usable year.
    """
    h = to_local_standard(hourly, standard_offset_h)
    n = len(h["time"])
    year, month, _day, hour = _calendar(h["time"])

    # NaN fraction per month group is judged before gaps are filled.
    isbad = np.zeros(n, dtype=bool)
    for k in _FS_KEYS:
        isbad |= ~np.isfinite(np.asarray(h[k], dtype=float))

    data = {
        k: _fill_gaps(
            h[k],
            circular=(k == "wind_direction_deg"),
            zero=(k == "precipitation_mm"),
        )
        for k in _OUT_KEYS
    }

    key = year * 100 + month
    # candidates[m] = list of (year, slice)
    candidates: dict[int, list[tuple[int, slice]]] = {m: [] for m in range(1, 13)}
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], n]
    for a, b in zip(starts, ends, strict=True):
        y, m = int(year[a]), int(month[a])
        dim = monthrange(y, m)[1]
        if b - a != dim * 24 or hour[a] != 0:
            continue  # partial month at either end of the record
        if np.count_nonzero(isbad[a:b]) / (b - a) > _MAX_NAN_FRACTION:
            continue
        candidates[m].append((y, slice(a, b)))

    chosen: list[tuple[int, slice]] = []
    for m in range(1, 13):
        cands = candidates[m]
        if not cands:
            raise ValueError(f"no complete, sufficiently gap-free year available for month {m}")
        if len(cands) == 1:
            chosen.append(cands[0])
            continue
        daily = [_daily_indices(data, sl) for _, sl in cands]
        score = np.zeros(len(cands))
        for name, wgt in _WEIGHTS.items():
            allv = np.sort(np.concatenate([d[name] for d in daily]))
            cdf = (np.arange(1, len(allv) + 1) - 0.5) / len(allv)
            for i, d in enumerate(daily):
                score[i] += wgt / 20.0 * _fs(d[name], allv, cdf)
        chosen.append(cands[int(np.argmin(score))])

    out = {k: [] for k in _OUT_KEYS}
    for m, (y, sl) in zip(range(1, 13), chosen, strict=True):
        for k in _OUT_KEYS:
            seg = data[k][sl]
            if m == 2 and monthrange(y, 2)[1] == 29:
                seg = seg[: 28 * 24]
            out[k].append(seg)
    result = {k: np.concatenate(v) for k, v in out.items()}
    assert all(len(v) == HOURS_PER_YEAR for v in result.values())

    years = [y for y, _ in chosen]
    joins = np.cumsum([d * 24 for d in _MONTH_DAYS])[:-1]
    half = _BLEND_HOURS // 2
    for mi, j in enumerate(joins):
        if years[mi] == years[mi + 1]:
            continue  # consecutive months of one real year are already continuous
        lo, hi = j - half, j + half  # blended span [lo, hi)
        frac = np.arange(1, _BLEND_HOURS + 1) / (_BLEND_HOURS + 1)
        for k in _BLEND_KEYS:
            a, b = result[k][lo - 1], result[k][hi]
            result[k][lo:hi] = a + (b - a) * frac
    return {"hourly": result, "months_from_years": [int(y) for y in years], "method": _METHOD}


def _frame(hourly: dict, standard_offset_h: float) -> pd.DataFrame:
    h = to_local_standard(hourly, standard_offset_h)
    df = pd.DataFrame({k: np.asarray(h[k], dtype=float) for k in _OUT_KEYS})
    df.index = pd.DatetimeIndex(h["time"].astype("datetime64[ns]"))
    return df


def _year_fraction(df: pd.DataFrame, col: str) -> float:
    """Years of valid data in `col`, so totals scale correctly for gaps/partial years."""
    return float(df[col].notna().sum()) / 8766.0


def monthly_summary(hourly: dict, standard_offset_h: float) -> list[dict]:
    """Twelve climatological month rows over the full record (local standard time)."""
    df = _frame(hourly, standard_offset_h)
    daily = df["temperature_c"].groupby(df.index.floor("D"))
    cnt = daily.count()
    dmax = daily.max()[cnt >= 20]
    dmin = daily.min()[cnt >= 20]
    rows = []
    for m in range(1, 13):
        sel = df[df.index.month == m]
        # Effective number of years of this month: valid hours / hours in a month.
        dim = float(monthrange(2001, m)[1] if m != 2 else 28.25)

        def total(col: str, scale: float = 1.0, sel=sel, dim=dim) -> float | None:
            valid = sel[col].dropna()
            if valid.empty:
                return None
            return float(valid.sum() * scale / (len(valid) / (dim * 24.0)))

        def mean(col: str, sel=sel) -> float | None:
            v = sel[col].mean()
            return None if not math.isfinite(v) else float(v)

        mx = dmax[dmax.index.month == m]
        mn = dmin[dmin.index.month == m]
        tmax, tmin = sel["temperature_c"].max(), sel["temperature_c"].min()
        rows.append(
            {
                "month": m,
                "temp_mean_c": mean("temperature_c"),
                "temp_mean_daily_max_c": float(mx.mean()) if len(mx) else None,
                "temp_mean_daily_min_c": float(mn.mean()) if len(mn) else None,
                "temp_record_max_c": float(tmax) if math.isfinite(tmax) else None,
                "temp_record_min_c": float(tmin) if math.isfinite(tmin) else None,
                "precip_mm": total("precipitation_mm"),
                "ghi_kwh_m2": total("ghi_wm2", 1.0 / 1000.0),
                "wind_mean_ms": mean("wind_speed_ms"),
                "rh_mean_pct": mean("relative_humidity_pct"),
            }
        )
    return rows


def _annual(hourly: dict, standard_offset_h: float) -> dict:
    df = _frame(hourly, standard_offset_h)
    daily = df["temperature_c"].groupby(df.index.floor("D"))
    dmean = daily.mean()[daily.count() >= 20]
    dyears = len(dmean) / 365.25 if len(dmean) else float("nan")
    hdd = float((HDD_CDD_BASE_C - dmean).clip(lower=0).sum() / dyears) if len(dmean) else None
    cdd = float((dmean - HDD_CDD_BASE_C).clip(lower=0).sum() / dyears) if len(dmean) else None

    def per_year(col: str, scale: float = 1.0) -> float | None:
        yrs = _year_fraction(df, col)
        return float(df[col].sum() * scale / yrs) if yrs > 0 else None

    mt = df["temperature_c"].mean()
    return {
        "hdd_18c": hdd,
        "cdd_18c": cdd,
        "ghi_kwh_m2": per_year("ghi_wm2", 1.0 / 1000.0),
        "mean_temp_c": float(mt) if math.isfinite(mt) else None,
        "precip_mm": per_year("precipitation_mm"),
    }


def _clean(v, nd: int = 1):
    """Round a number for JSON; NaN/inf/None become None."""
    if v is None:
        return None
    v = float(v)
    return round(v, nd) if math.isfinite(v) else None


def _clean_list(arr: np.ndarray, nd: int) -> list[float | None]:
    return [_clean(v, nd) for v in np.asarray(arr, dtype=float).tolist()]


def climate_summary(climate_layer) -> dict:
    """The JSON-safe climate block served by the web API.

    Keys are a fixed contract: source, timezone, typical_year, monthly, annual.
    """
    d = climate_layer.data
    tz = d["timezone"]
    offset = tz["standard_offset_h"]
    src = climate_layer.sources[0] if climate_layer.sources else None
    ty = typical_year(d["hourly"], offset)
    monthly = monthly_summary(d["hourly"], offset)
    annual = _annual(d["hourly"], offset)
    return {
        "source": {
            "name": src.name if src else None,
            "period": d.get("period"),
            "grid_point_lonlat": [float(x) for x in d["grid_point_lonlat"]],
            "elevation_m": _clean(d.get("elevation_m"), 1),
            "licence": src.licence if src else None,
            "note": src.note if src else None,
        },
        "timezone": dict(tz),
        "typical_year": {
            "months_from_years": ty["months_from_years"],
            "method": ty["method"],
            "hourly": {
                k: _clean_list(v, 0 if k == "wind_direction_deg" else 1) for k, v in ty["hourly"].items()
            },
        },
        "monthly": [{k: (v if k == "month" else _clean(v, 2)) for k, v in row.items()} for row in monthly],
        "annual": {k: _clean(v, 1) for k, v in annual.items()},
    }
