"""Open-Meteo ERA5 archive climate provider.

Keyless reanalysis pull for the AOI centroid: three complete calendar years,
hourly. ERA5 is a ~31 km native product resampled by Open-Meteo onto a ~9 km
grid and then reported at the nearest ~3 km interpolated point — this is
regional climate, not a site microclimate, and the note below records both the
requested and the returned grid-point coordinates so nobody mistakes one for
the other.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import requests

from ..registry import REGISTRY
from ..types import LayerResult, Provider, Source

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = "temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation"
YEARS_OF_RECORD = 3
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


class OpenMeteoProvider(Provider):
    """3 complete calendar years of ERA5 hourly data at the AOI centroid."""

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
            resp = requests.get(ARCHIVE_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json(), {
                "url": resp.url,
                "requested_lonlat": [lon, lat],
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

        payload, meta = cache.get_json(key, _producer)

        hourly = payload["hourly"]
        temps = np.asarray(hourly["temperature_2m"], dtype=float)
        wind_kmh = np.asarray(hourly["wind_speed_10m"], dtype=float)
        wind_dir = np.asarray(hourly["wind_direction_10m"], dtype=float)
        ghi_wm2 = np.asarray(hourly["shortwave_radiation"], dtype=float)
        n_years = end_year - start_year + 1

        n_days = temps.size // 24
        daily_mean = temps[: n_days * 24].reshape(n_days, 24).mean(axis=1)
        hdd_total = float(np.clip(HDD_CDD_BASE_C - daily_mean, 0, None).sum())
        cdd_total = float(np.clip(daily_mean - HDD_CDD_BASE_C, 0, None).sum())
        ghi_kwh_total = float(ghi_wm2.sum()) / 1000.0

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
