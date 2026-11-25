"""Open-Meteo ERA5 archive climate provider.

Keyless reanalysis pull for the AOI centroid: ten complete calendar years,
hourly, with every variable an EnergyPlus weather file needs, so the same pull
feeds the sheet's summary figures, the web app's climate charts and the EPW
export (a typical year chosen month by month from the record).

ERA5 is a ~31 km native product resampled by Open-Meteo onto a ~9 km grid and
reported at the nearest ~3 km interpolated point. This is regional climate, not
a site microclimate, and the note below records both the requested and the
returned grid-point coordinates so nobody mistakes one for the other.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import requests

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = (
    "temperature_2m,dew_point_2m,relative_humidity_2m,surface_pressure,"
    "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,"
    "wind_speed_10m,wind_direction_10m,cloud_cover,precipitation"
)
# Ten years: enough for a typical-month selection to mean something, while one
# archive request stays a few seconds.
YEARS_OF_RECORD = 10
HDD_CDD_BASE_C = 18.0
KMH_TO_MS = 1000.0 / 3600.0

# 16-point compass, centred bins 22.5 degrees wide starting at N.
DIRECTION_LABELS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]
SPEED_BIN_EDGES_MS = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, float("inf")]
SPEED_BIN_LABELS = ["0-2", "2-4", "4-6", "6-8", "8-10", "10+"]


def _last_complete_year() -> int:
    """The most recent calendar year that has certainly finished, in UTC.

    Local date would make the period machine-dependent: two runs either side of
    midnight in different timezones would request different years and cache the
    result under the same key. ERA5 also lags real time by several days, so the
    conservative boundary costs nothing.
    """
    today = datetime.now(UTC).date()
    return today.year - 1 if today.month > 1 or today.day > 1 else today.year - 2


def _timezone(lon: float, lat: float, cache) -> dict:
    """IANA zone and its *standard* (non-DST) UTC offset for the site.

    EPW files and solar geometry use local standard time all year. One tiny
    Open-Meteo request with `timezone=auto` resolves the zone name; the standard
    offset comes from zoneinfo in mid-January (or mid-July south of the equator,
    where January is summer time).
    """
    from zoneinfo import ZoneInfo

    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": "2020-01-01",
        "end_date": "2020-01-01",
        "hourly": "temperature_2m",
        "timezone": "auto",
    }
    key = cache.key("open-meteo-timezone", round(lon, 4), round(lat, 4))

    def _producer() -> tuple[dict, dict]:
        resp = requests.get(ARCHIVE_URL, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        return {"timezone": body.get("timezone")}, {"url": resp.url}

    try:
        name = cache.get_json(key, _producer)[0].get("timezone")
        zone = ZoneInfo(name)
        probe = datetime(2021, 1, 15, 12, tzinfo=zone) if lat >= 0 else datetime(2021, 7, 15, 12, tzinfo=zone)
        dst = probe.dst()
        offset = probe.utcoffset() - dst if dst else probe.utcoffset()
        return {"name": name, "standard_offset_h": offset.total_seconds() / 3600.0, "approximate": False}
    except Exception:
        # Solar time zone as a last resort; flagged so nobody mistakes it for civil time.
        return {"name": None, "standard_offset_h": float(round(lon / 15.0)), "approximate": True}


def _hourly_arrays(hourly: dict) -> dict[str, np.ndarray]:
    """Open-Meteo hourly JSON -> SI arrays with stable names (UTC timestamps)."""

    def arr(name: str) -> np.ndarray:
        return np.asarray([np.nan if v is None else v for v in hourly.get(name, [])], dtype=float)

    return {
        "time": np.asarray(hourly["time"], dtype="datetime64[m]"),
        "temperature_c": arr("temperature_2m"),
        "dew_point_c": arr("dew_point_2m"),
        "relative_humidity_pct": arr("relative_humidity_2m"),
        "pressure_pa": arr("surface_pressure") * 100.0,
        "ghi_wm2": arr("shortwave_radiation"),
        "dni_wm2": arr("direct_normal_irradiance"),
        "dhi_wm2": arr("diffuse_radiation"),
        "wind_speed_ms": arr("wind_speed_10m") * KMH_TO_MS,
        "wind_direction_deg": arr("wind_direction_10m"),
        "cloud_cover_pct": arr("cloud_cover"),
        "precipitation_mm": arr("precipitation"),
    }


class OpenMeteoProvider(Provider):
    """Ten complete calendar years of ERA5 hourly data at the AOI centroid."""

    name = "open_meteo"
    layer = "climate"
    licence = "CC BY 4.0 (Open-Meteo; free tier is non-commercial)"
    rank = 10
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        lon, lat = aoi.centroid_lonlat
        end_year = _last_complete_year()
        start_year = end_year - (YEARS_OF_RECORD - 1)
        start_date = f"{start_year}-01-01"
        end_date = f"{end_year}-12-31"

        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "start_date": start_date,
            "end_date": end_date,
            "hourly": HOURLY_VARS,
            "timezone": "UTC",
        }
        key = cache.key("open-meteo-archive", lon, lat, start_date, end_date, HOURLY_VARS)

        def _producer() -> tuple[dict, dict]:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json(), {
                "url": resp.url,
                "requested_lonlat": [lon, lat],
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

        payload, meta = cache.get_json(key, _producer)

        hourly = payload["hourly"]
        series = _hourly_arrays(hourly)
        temps = series["temperature_c"]
        wind_kmh = series["wind_speed_ms"] / KMH_TO_MS
        wind_dir = series["wind_direction_deg"]
        ghi_wm2 = series["ghi_wm2"]
        n_years = end_year - start_year + 1

        n_days = temps.size // 24
        daily_mean = np.nanmean(temps[: n_days * 24].reshape(n_days, 24), axis=1)
        hdd_total = float(np.clip(HDD_CDD_BASE_C - daily_mean, 0, None).sum())
        cdd_total = float(np.clip(daily_mean - HDD_CDD_BASE_C, 0, None).sum())
        ghi_kwh_total = float(np.nansum(ghi_wm2)) / 1000.0

        wind_ms = wind_kmh * KMH_TO_MS
        rose = self._wind_rose(wind_ms, wind_dir)

        returned_lon = payload.get("longitude")
        returned_lat = payload.get("latitude")

        source = Source(
            name="Open-Meteo ERA5 archive",
            url=meta.get("url", ARCHIVE_URL),
            licence=self.licence,
            licence_url="https://open-meteo.com/en/license",
            note=(
                f"Requested centroid ({lon:.4f}, {lat:.4f}); Open-Meteo snapped to its nearest "
                f"grid point ({returned_lon}, {returned_lat}). ERA5 is a ~3 km-resolved reanalysis "
                "product: this is regional climate, not a site microclimate. Free API tier is "
                "non-commercial and capped near 10,000 calls/day."
            ),
            commercial_ok=True,
        )

        return LayerResult(
            layer=self.layer,
            provider=self.name,
            data={
                "period": f"{start_date} to {end_date}",
                "years": n_years,
                "hdd_18c_annual_mean": hdd_total / n_years,
                "cdd_18c_annual_mean": cdd_total / n_years,
                "ghi_kwh_m2_annual": ghi_kwh_total / n_years,
                "mean_temperature_c": float(np.nanmean(temps)),
                "wind_rose": rose,
                "requested_lonlat": [lon, lat],
                "grid_point_lonlat": [returned_lon, returned_lat],
                "elevation_m": payload.get("elevation"),
                "timezone": _timezone(lon, lat, cache),
                # Full hourly record (UTC). Consumers: sce.export.epw, the web API.
                "hourly": series,
            },
            sources=[source],
            coverage=1.0,
            degraded=False,
            notes=[
                "Free Open-Meteo API tier is non-commercial and capped near 10,000 calls/day; "
                "a commercial deployment needs a paid Open-Meteo plan.",
                "ERA5 snaps to a coarse reanalysis grid: requested and returned coordinates "
                "differ (see source note) and this is regional, not site-level, climate.",
            ],
        )

    @staticmethod
    def _wind_rose(speed_ms: np.ndarray, direction_deg: np.ndarray) -> dict:
        """16 direction bins x speed bins, frequencies over all valid hours summing to 1.0."""
        valid = ~(np.isnan(speed_ms) | np.isnan(direction_deg))
        speed_ms = speed_ms[valid]
        direction_deg = direction_deg[valid]

        dir_bin_width = 360.0 / len(DIRECTION_LABELS)
        dir_idx = np.floor(((direction_deg + dir_bin_width / 2.0) % 360.0) / dir_bin_width).astype(int)
        speed_idx = np.digitize(speed_ms, SPEED_BIN_EDGES_MS[1:-1], right=False)

        total = max(speed_ms.size, 1)
        table = np.zeros((len(DIRECTION_LABELS), len(SPEED_BIN_LABELS)), dtype=float)
        for d, s in zip(dir_idx, speed_idx, strict=False):
            table[d, s] += 1.0
        table /= total

        return {
            "direction_labels": DIRECTION_LABELS,
            "speed_bin_labels": SPEED_BIN_LABELS,
            "speed_bin_edges_ms": SPEED_BIN_EDGES_MS,
            "frequencies": table.tolist(),
            "frequency_sum_check": float(table.sum()),
        }


REGISTRY.register(OpenMeteoProvider())
