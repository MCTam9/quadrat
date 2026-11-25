"""Live check of the EA LiDAR WCS: a small London AOI returns plausible heights."""

from __future__ import annotations

import numpy as np
import pytest

from sce.aoi import AOI
from sce.cache import Cache
from sce.providers.height_ea_lidar import EaLidarBuildingHeightProvider

pytestmark = pytest.mark.live


def test_ea_lidar_london_heights_plausible(tmp_path):
    aoi = AOI.from_point(-0.128, 51.507, 250.0, name="trafalgar")
    res = EaLidarBuildingHeightProvider().fetch(aoi, Cache(tmp_path, offline=False))
    assert res.raster["kind"] == "ndsm"
    assert res.coverage > 0.8
    arr = res.raster["array"]
    tall = arr[np.isfinite(arr) & (arr > 2.0)]
    assert tall.size > 1000
    assert 2.0 <= res.data["mean_height_m"] <= 300.0
    assert float(np.nanmax(arr)) <= 300.0
