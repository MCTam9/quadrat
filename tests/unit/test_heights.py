"""LiDAR height enrichment on a synthetic nDSM with analytically known heights."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from affine import Affine
from shapely.geometry import box

from sce.heights import enrich_building_heights
from sce.types import LayerResult

CRS = "EPSG:32630"


def _layers(prefer_kind: str = "ndsm"):
    # 100 x 100 m at 1 m cells, origin (0, 100). Building A (20x20) is 12 m tall
    # with a 15 m chimney-free flat roof; B is tagged 7 m; C is 2x2 m (4 cells).
    arr = np.zeros((100, 100), dtype=np.float32)
    transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 100.0)
    arr[40:60, 10:30] = 12.0  # A: x 10..30, y 40..60
    arr[40:60, 50:70] = 30.0  # B: huge LiDAR value that tagged height must beat
    arr[70:72, 80:82] = 20.0  # C: 4 cells only
    gdf = gpd.GeoDataFrame(
        {
            "height_m": [np.nan, 7.0, np.nan],
            "height_source": [None, "tag", None],
        },
        geometry=[box(10, 40, 30, 60), box(50, 40, 70, 60), box(80, 28, 82, 30)],
        crs=CRS,
    )
    raster = {
        "array": arr,
        "transform": transform,
        "crs": CRS,
        "nodata": float("nan"),
        "res": (1.0, 1.0),
        "kind": prefer_kind,
    }
    return {
        "buildings": LayerResult(layer="buildings", provider="osm", gdf=gdf, coverage=1 / 3),
        "building_height": LayerResult(layer="building_height", provider="lidar", raster=raster),
    }


def test_samples_untagged_keeps_tagged_and_leaves_small_unknown():
    out = enrich_building_heights(_layers())
    g = out["buildings"].gdf
    assert g.height_m.iloc[0] == pytest.approx(12.0)
    assert g.height_source.iloc[0] == "lidar"
    assert g.height_m.iloc[1] == 7.0
    assert g.height_source.iloc[1] == "tag"
    assert np.isnan(g.height_m.iloc[2])
    assert pd.isna(g.height_source.iloc[2])


def test_coverage_recomputed():
    out = enrich_building_heights(_layers())
    assert out["buildings"].coverage == pytest.approx(2 / 3)


def test_prefer_lidar_replaces_tag():
    g = enrich_building_heights(_layers(), prefer_lidar=True)["buildings"].gdf
    assert g.height_m.iloc[1] == pytest.approx(30.0)
    assert g.height_source.iloc[1] == "lidar"


def test_inputs_not_mutated():
    layers = _layers()
    before = layers["buildings"].gdf.copy()
    out = enrich_building_heights(layers)
    assert out["buildings"] is not layers["buildings"]
    assert layers["buildings"].coverage == pytest.approx(1 / 3)
    assert layers["buildings"].gdf.equals(before)
    assert np.isnan(layers["buildings"].gdf.height_m.iloc[0])


def test_non_ndsm_raster_is_a_no_op():
    layers = _layers(prefer_kind="anbh")
    out = enrich_building_heights(layers)
    assert out["buildings"] is layers["buildings"]


def test_stale_low_coverage_note_dropped_once_lidar_fills_gaps():
    """The provider's 'fewer than half' note must not survive enrichment that fixed it."""
    layers = _layers()
    layers["buildings"].notes = ["fewer than half of buildings have a known height"]
    out = enrich_building_heights(layers)
    assert out["buildings"].coverage >= 0.5
    assert not any("known height" in n for n in out["buildings"].notes)
