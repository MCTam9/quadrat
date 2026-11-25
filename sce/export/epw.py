"""EnergyPlus weather (EPW) export from the climate layer's typical year.

A typical year chosen month by month from ten years of ERA5 reanalysis (see
sce/climate.py). It is regional reanalysis at one grid point, not a site
microclimate, and the file's COMMENTS lines say so.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..climate import typical_year
from ..types import LayerResult

_SIGMA = 5.670374419e-8
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_FLAGS = "?0" * 21


def _horizontal_ir(temp_c: np.ndarray, dew_c: np.ndarray, opaque_tenths: np.ndarray) -> np.ndarray:
    """Horizontal infrared from dry bulb, dew point and opaque sky cover (tenths).

    EnergyPlus sky emissivity: (0.787 + 0.764 ln(Tdew/273)) * (1 + 0.0224 N
    - 0.0035 N^2 + 0.00028 N^3), then eps * sigma * T^4 (Wh/m2).
    """
    tk = temp_c + 273.15
    tdk = np.maximum(dew_c + 273.15, 150.0)
    n = opaque_tenths
    eps = (0.787 + 0.764 * np.log(tdk / 273.0)) * (1 + 0.0224 * n - 0.0035 * n**2 + 0.00028 * n**3)
    return eps * _SIGMA * tk**4


def _num(x: float, nd: int, missing: str) -> str:
    return missing if not math.isfinite(x) else f"{x:.{nd}f}"


def write_epw(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write a typical-year EPW to `path` and return it."""
    layer = layers.get("climate") if layers else None
    if layer is None or layer.data is None:
        raise ValueError("EPW export needs a climate layer; none was fetched")
    data = layer.data
    if not data.get("hourly") or "temperature_c" not in data["hourly"]:
        raise ValueError("EPW export needs hourly climate data; the climate layer has none")

    tz = data["timezone"]
    ty = typical_year(data["hourly"], tz["standard_offset_h"])
    h, years = ty["hourly"], ty["months_from_years"]
    src = layer.sources[0] if layer.sources else None

    glon, glat = data["grid_point_lonlat"]
    elev = data.get("elevation_m") or 0.0
    city = str(aoi.name).replace(",", " ")
    header = [
        f"LOCATION,{city},-,-,ERA5-OpenMeteo,999999,{glat:.4f},{glon:.4f},{tz['standard_offset_h']:.1f},{elev:.1f}",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,"
        + ", ".join(
            [
                f"Source: {src.name if src else 'Open-Meteo ERA5 archive'} ({data.get('period', '')})",
                f"Licence: {src.licence if src else 'CC BY 4.0'}",
                "regional ERA5 reanalysis, not site microclimate",
            ]
        ).replace("\n", " "),
        "COMMENTS 2,Typical year built month by month (Finkelstein-Schafer). Source year per month: "
        + ", ".join(f"{m}={y}" for m, y in zip(_MONTHS, years, strict=True)),
        "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
    ]

    cloud = np.clip(np.round(h["cloud_cover_pct"] / 10.0), 0, 10)
    ir = _horizontal_ir(h["temperature_c"], h["dew_point_c"], cloud)
    rows = []
    i = 0
    for mi, dim in enumerate(_MONTH_DAYS):
        for d in range(1, dim + 1):
            for hr in range(24):
                rh = min(max(h["relative_humidity_pct"][i], 0.0), 110.0)
                fields = [
                    str(years[mi]),
                    str(mi + 1),
                    str(d),
                    str(hr + 1),
                    "60",
                    _FLAGS,
                    _num(h["temperature_c"][i], 1, "99.9"),
                    _num(h["dew_point_c"][i], 1, "99.9"),
                    _num(rh, 0, "999"),
                    _num(h["pressure_pa"][i], 0, "999999"),
                    "9999",
                    "9999",
                    _num(ir[i], 0, "9999"),
                    _num(max(h["ghi_wm2"][i], 0.0), 0, "9999"),
                    _num(max(h["dni_wm2"][i], 0.0), 0, "9999"),
                    _num(max(h["dhi_wm2"][i], 0.0), 0, "9999"),
                    "999999",
                    "999999",
                    "999999",
                    "9999",
                    _num(h["wind_direction_deg"][i], 0, "999"),
                    _num(h["wind_speed_ms"][i], 1, "999"),
                    str(int(cloud[i])),
                    str(int(cloud[i])),
                    "9999",
                    "99999",
                    "9",
                    "999999999",
                    "999",
                    "0.999",
                    "999",
                    "99",
                    "999",
                    _num(max(h["precipitation_mm"][i], 0.0), 1, "999"),
                    "1",
                ]
                rows.append(",".join(fields))
                i += 1
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header + rows) + "\n", encoding="utf-8")
    return path
