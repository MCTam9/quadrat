"""EPW export: structure, format and (optionally) a ladybug round trip."""

from __future__ import annotations

import numpy as np
import pytest
from test_climate_typical import synthetic_hourly

from sce.aoi import AOI
from sce.climate import typical_year
from sce.export.epw import write_epw
from sce.types import LayerResult, Source


def _layers():
    data = {
        "hourly": synthetic_hourly(),
        "timezone": {"name": "Europe/London", "standard_offset_h": 0.0, "approximate": False},
        "elevation_m": 25.0,
        "grid_point_lonlat": [-0.1, 51.5],
        "period": "2019-01-01 to 2021-12-31",
    }
    src = Source(name="Open-Meteo ERA5", url="https://open-meteo.com", licence="CC BY 4.0")
    return {"climate": LayerResult(layer="climate", provider="open_meteo", data=data, sources=[src])}


@pytest.fixture
def epw_lines(tmp_path):
    aoi = AOI.from_point(-0.1276, 51.5072, 300, name="Test Site")
    p = write_epw(tmp_path / "x.epw", _layers(), aoi)
    return p, p.read_text().splitlines()


def test_header_and_rows(epw_lines):
    _, lines = epw_lines
    assert len(lines) == 8 + 8760
    assert lines[0].startswith("LOCATION,Test Site,-,-,ERA5-OpenMeteo,999999,51.5000,-0.1000,0.0,25.0")
    assert lines[1] == "DESIGN CONDITIONS,0"
    assert lines[6].startswith("COMMENTS 2,") and "Jan=" in lines[6]
    assert "not site microclimate" in lines[5]
    assert lines[7] == "DATA PERIODS,1,1,Data,Sunday,1/1,12/31"
    rows = [ln.split(",") for ln in lines[8:]]
    assert all(len(r) == 35 for r in rows)
    assert [int(r[3]) for r in rows[:24]] == list(range(1, 25))
    assert not any(r[1] == "2" and r[2] == "29" for r in rows)
    assert rows[0][1:4] == ["1", "1", "1"]
    assert rows[-1][1:4] == ["12", "31", "24"]


def test_missing_climate_raises(tmp_path):
    aoi = AOI.from_point(0, 51, 100)
    with pytest.raises(ValueError, match="climate"):
        write_epw(tmp_path / "a.epw", {}, aoi)
    empty = {"climate": LayerResult(layer="climate", provider="p", data={"hourly": {}})}
    with pytest.raises(ValueError, match="hourly"):
        write_epw(tmp_path / "a.epw", empty, aoi)


def test_ladybug_roundtrip(epw_lines):
    pytest.importorskip("ladybug")
    from ladybug.epw import EPW

    path, _ = epw_lines
    epw = EPW(str(path))
    ours = typical_year(_layers()["climate"].data["hourly"], 0.0)["hourly"]["temperature_c"]
    assert len(epw.dry_bulb_temperature) == 8760
    assert abs(np.mean(epw.dry_bulb_temperature.values) - ours.mean()) < 0.05
