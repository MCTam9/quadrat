"""The georef sidecar must let any file in a bundle be put back on the earth."""

from __future__ import annotations

import json

from sce.aoi import AOI
from sce.export._georef import local_origin, write_georef


def test_georef_sidecar(tmp_path):
    aoi = AOI.from_point(-0.1, 51.5, 500.0, name="g")
    p = write_georef(tmp_path / "georef.json", aoi)
    data = json.loads(p.read_text())
    assert data["crs"] == aoi.epsg == "EPSG:32630"
    assert data["units"] == "metre"
    ox, oy = local_origin(aoi)
    assert data["local_origin"]["easting"] == ox
    assert abs(ox - aoi.geometry.centroid.x) < 0.01
    assert p.with_suffix(".prj").read_text().startswith("PROJCS")
