"""Solar geometry for the sun-path diagram.

Implemented from the NOAA solar position algorithm rather than pulled from a
library, because the only dependency it needs is numpy and because the sun path
is the one panel on a site sheet whose absence an architect notices immediately.

Accuracy is well under a degree for the years and latitudes this tool covers,
which is far finer than the line weight it is drawn with.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Solstices and equinoxes are drawn as the three canonical arcs; every architect
# reads a sun path by these three lines and nothing else.
KEY_DAYS = {
    "21 Jun": 172,
    "21 Mar / 23 Sep": 80,
    "21 Dec": 355,
}


@dataclass(frozen=True)
class SunPositions:
    """Azimuth and altitude in degrees. Azimuth is clockwise from true north."""

    azimuth: np.ndarray
    altitude: np.ndarray
    hours: np.ndarray

    @property
    def above_horizon(self) -> np.ndarray:
        return self.altitude > 0


def _fractional_year(day_of_year: np.ndarray, hour: np.ndarray) -> np.ndarray:
    return 2 * np.pi / 365.0 * (day_of_year - 1 + (hour - 12) / 24.0)


def _equation_of_time(gamma: np.ndarray) -> np.ndarray:
    """Minutes. The difference between apparent and mean solar time."""
    return 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )


def _declination(gamma: np.ndarray) -> np.ndarray:
    """Radians."""
    return (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )


def solar_position(
    lat: float,
    lon: float,
    day_of_year: np.ndarray | int,
    hour_local: np.ndarray | float,
    utc_offset_hours: float | None = None,
) -> SunPositions:
    """Sun azimuth and altitude for a day and local clock hour.

    `utc_offset_hours` defaults to the longitude's mean solar offset, which is
    what you want for a site diagram: it centres solar noon on the plot rather
    than on a political timezone boundary.
    """
    if utc_offset_hours is None:
        utc_offset_hours = lon / 15.0

    doy = np.asarray(day_of_year, dtype=float)
    hour = np.asarray(hour_local, dtype=float)
    doy, hour = np.broadcast_arrays(doy, hour)

    gamma = _fractional_year(doy, hour)
    eqtime = _equation_of_time(gamma)
    decl = _declination(gamma)

    time_offset = eqtime + 4.0 * lon - 60.0 * utc_offset_hours
    true_solar_time = hour * 60.0 + time_offset
    hour_angle = np.radians(true_solar_time / 4.0 - 180.0)

    lat_r = np.radians(lat)
    cos_zenith = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hour_angle)
    cos_zenith = np.clip(cos_zenith, -1.0, 1.0)
    zenith = np.arccos(cos_zenith)
    altitude = 90.0 - np.degrees(zenith)

    sin_zenith = np.sin(zenith)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos_az = (np.sin(lat_r) * cos_zenith - np.sin(decl)) / (np.cos(lat_r) * sin_zenith)
    cos_az = np.clip(np.nan_to_num(cos_az, nan=1.0), -1.0, 1.0)
    azimuth = np.degrees(np.arccos(cos_az))
    azimuth = np.where(hour_angle > 0, 360.0 - azimuth, azimuth)

    return SunPositions(azimuth=azimuth, altitude=altitude, hours=hour)


def day_arc(lat: float, lon: float, day_of_year: int, step_minutes: int = 5) -> SunPositions:
    """One day's path, sampled finely enough to draw as a smooth curve."""
    hours = np.arange(0.0, 24.0, step_minutes / 60.0)
    return solar_position(lat, lon, day_of_year, hours)


def analemma_points(lat: float, lon: float, hour_local: float) -> SunPositions:
    """The figure-of-eight traced by the sun at a fixed clock hour across a year.

    Drawn faintly, these are the hour markers that let a reader find 09:00 or
    15:00 on the chart without a legend.
    """
    days = np.arange(1, 366, 5.0)
    return solar_position(lat, lon, days, np.full_like(days, hour_local))


def key_arcs(lat: float, lon: float) -> dict[str, SunPositions]:
    return {label: day_arc(lat, lon, doy) for label, doy in KEY_DAYS.items()}


def sun_hours(lat: float, lon: float, day_of_year: int) -> float:
    """Hours of sun above the horizon. Used as a label on the solstice arcs."""
    arc = day_arc(lat, lon, day_of_year, step_minutes=1)
    return float(np.count_nonzero(arc.above_horizon) / 60.0)


def stereographic(azimuth_deg: np.ndarray, altitude_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project to the stereographic sun-path chart architects expect.

    North at the top, radius 1 at the horizon, 0 at the zenith. Stereographic
    rather than equidistant because it preserves the shape of the arcs near the
    horizon, where overshadowing questions actually live.
    """
    alt = np.radians(np.asarray(altitude_deg, dtype=float))
    r = np.tan((np.pi / 2 - alt) / 2.0)
    az = np.radians(np.asarray(azimuth_deg, dtype=float))
    return r * np.sin(az), r * np.cos(az)
