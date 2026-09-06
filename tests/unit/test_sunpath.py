"""Solar geometry checks against values that can be derived by hand.

Every assertion here is a number an architect could verify with a table, which
is the point: the sun path is the panel a reader will trust or dismiss the whole
sheet by, so none of it is snapshotted.
"""

from __future__ import annotations

import numpy as np
import pytest

from sce.report.sunpath import day_arc, solar_position, stereographic, sun_hours

TROPIC = 23.44  # obliquity of the ecliptic, in degrees

SITES = [
    ("london", 51.5074, -0.1276),
    ("tashkent", 41.2995, 69.2401),
    ("riyadh", 24.7136, 46.6753),
]


@pytest.mark.parametrize("name,lat,lon", SITES, ids=[s[0] for s in SITES])
def test_summer_solstice_noon_altitude_matches_the_hand_calculation(name, lat, lon):
    """Noon altitude on 21 June is 90 - latitude + obliquity."""
    arc = day_arc(lat, lon, 172, step_minutes=1)
    assert arc.altitude.max() == pytest.approx(90.0 - lat + TROPIC, abs=0.4)


@pytest.mark.parametrize("name,lat,lon", SITES, ids=[s[0] for s in SITES])
def test_winter_solstice_noon_altitude_matches_the_hand_calculation(name, lat, lon):
    """Noon altitude on 21 December is 90 - latitude - obliquity."""
    arc = day_arc(lat, lon, 355, step_minutes=1)
    assert arc.altitude.max() == pytest.approx(90.0 - lat - TROPIC, abs=0.4)


@pytest.mark.parametrize("name,lat,lon", SITES, ids=[s[0] for s in SITES])
def test_the_sun_crosses_due_south_at_its_highest(name, lat, lon):
    """The bug this test exists for: an azimuth measured from the wrong
    reference puts the midday sun in the northern sky, which silently mirrors
    the whole sun path and every overshadowing conclusion drawn from it.

    Stated as a crossing rather than an equality because near the zenith the
    azimuth sweeps through south almost instantly - at Riyadh in June the sun
    passes within 1.3 degrees of overhead, and any finite sampling step lands
    beside 180 rather than on it. The crossing is exact regardless.
    """
    arc = day_arc(lat, lon, 172, step_minutes=1)
    peak = int(np.argmax(arc.altitude))
    before = float(arc.azimuth[peak - 1])
    after = float(arc.azimuth[peak + 1])
    assert before < 180.0 < after, (
        f"{name}: sun does not cross due south at its highest (azimuth went {before:.1f} -> {after:.1f})"
    )


def test_summer_sun_rises_north_of_east_and_sets_north_of_west():
    """At mid latitudes in June the sun rises and sets on the northern side."""
    arc = day_arc(51.5074, -0.1276, 172, step_minutes=1)
    up = arc.above_horizon
    assert float(arc.azimuth[up][0]) < 90.0
    assert float(arc.azimuth[up][-1]) > 270.0


def test_winter_sun_rises_south_of_east_and_sets_south_of_west():
    arc = day_arc(51.5074, -0.1276, 355, step_minutes=1)
    up = arc.above_horizon
    assert 90.0 < float(arc.azimuth[up][0]) < 180.0
    assert 180.0 < float(arc.azimuth[up][-1]) < 270.0


def test_equator_equinox_sun_passes_close_to_the_zenith():
    arc = day_arc(0.0, 0.0, 80, step_minutes=1)
    assert arc.altitude.max() > 89.0


def test_equinox_gives_roughly_twelve_hours_everywhere():
    for _, lat, lon in SITES:
        assert sun_hours(lat, lon, 80) == pytest.approx(12.0, abs=0.35)


def test_daylight_hours_are_longer_in_summer_than_winter():
    for _, lat, lon in SITES:
        assert sun_hours(lat, lon, 172) > sun_hours(lat, lon, 355)


def test_southern_hemisphere_noon_is_due_north():
    """Sydney's midday sun sits in the northern sky; the projection must not
    quietly assume a northern-hemisphere site."""
    arc = day_arc(-33.87, 151.21, 355, step_minutes=1)
    noon_azimuth = float(arc.azimuth[int(np.argmax(arc.altitude))])
    assert min(noon_azimuth, 360.0 - noon_azimuth) == pytest.approx(0.0, abs=2.0)


def test_stereographic_puts_the_horizon_on_the_unit_circle():
    x, y = stereographic(np.array([0.0, 90.0, 180.0, 270.0]), np.zeros(4))
    assert np.hypot(x, y) == pytest.approx(np.ones(4), abs=1e-9)


def test_stereographic_puts_north_up_and_south_down():
    x, y = stereographic(np.array([0.0, 180.0]), np.array([10.0, 10.0]))
    assert y[0] > 0 and y[1] < 0
    assert x == pytest.approx(np.zeros(2), abs=1e-9)


def test_zenith_projects_to_the_centre():
    x, y = stereographic(np.array([123.0]), np.array([90.0]))
    assert np.hypot(x, y) == pytest.approx(0.0, abs=1e-9)


def test_every_daylight_point_falls_inside_the_horizon_circle():
    for _, lat, lon in SITES:
        for doy in (172, 80, 355):
            arc = day_arc(lat, lon, doy)
            up = arc.above_horizon
            x, y = stereographic(arc.azimuth[up], arc.altitude[up])
            assert np.hypot(x, y).max() <= 1.0 + 1e-9


def test_solar_position_broadcasts_a_day_against_many_hours():
    pos = solar_position(51.5, 0.0, 172, np.arange(0.0, 24.0, 0.5))
    assert pos.altitude.shape == (48,)
