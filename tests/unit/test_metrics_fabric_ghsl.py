"""GHSL building-height FALLBACK for floor space index.

`sce/providers/height_ghsl.py` exists precisely because OSM height coverage
on real sheets (Tashkent ~10%, Riyadh ~1%) is too sparse to trust. These
tests pin the three cases the contract calls out: OSM coverage sufficient
(GHSL ignored even if present), OSM coverage insufficient with GHSL present
(FSI computed and labelled GHSL), and neither present (FSI stays None).
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from sce.aoi import AOI
from sce.metrics.fabric import LEVEL_HEIGHT_M, fabric_metrics
from sce.types import LayerResult


def _aoi(radius: float = 100.0) -> AOI:
    return AOI.from_point(0.0, 51.0, radius, name="fabric-ghsl")


def _buildings(aoi: AOI, coverage: float) -> LayerResult:
    gdf = gpd.GeoDataFrame({"height_m": [9.0]}, geometry=[box(0, 0, 10, 10)], crs=aoi.crs)
    return LayerResult(layer="buildings", provider="synthetic", gdf=gdf, coverage=coverage)


def _ghsl(mean_height_m: float) -> LayerResult:
    return LayerResult(
        layer="building_height",
        provider="ghsl_building_height",
        data={"mean_height_m": mean_height_m},
        coverage=1.0,
    )


def test_ghsl_ignored_when_osm_coverage_sufficient():
    aoi = _aoi()
    buildings = _buildings(aoi, coverage=0.9)
    ghsl = _ghsl(mean_height_m=50.0)  # wildly different from the OSM height, so any leak is visible

    result = fabric_metrics({"buildings": buildings, "building_height": ghsl}, aoi)

    expected_fsi = (10 * 10 * (9.0 / LEVEL_HEIGHT_M)) / aoi.area_m2
    assert result["fsi"] == pytest.approx(expected_fsi)
    assert "GHSL" not in result["fsi_source"]
    assert "OSM" in result["fsi_source"] or "height" in result["fsi_source"]


def test_ghsl_fallback_used_when_osm_coverage_insufficient():
    aoi = _aoi()
    coverage = 0.1
    buildings = _buildings(aoi, coverage=coverage)
    mean_height = 12.0
    ghsl = _ghsl(mean_height_m=mean_height)

    result = fabric_metrics({"buildings": buildings, "building_height": ghsl}, aoi)

    footprint_area = 10 * 10
    expected_fsi = (footprint_area * (mean_height / LEVEL_HEIGHT_M)) / aoi.area_m2
    assert result["fsi"] == pytest.approx(expected_fsi)
    assert result["fsi"] is not None
    assert "GHSL" in result["fsi_source"]
    assert f"{coverage:.2f}" in result["fsi_source"]


def test_fsi_stays_none_when_neither_source_available():
    aoi = _aoi()
    coverage = 0.1
    buildings = _buildings(aoi, coverage=coverage)

    result = fabric_metrics({"buildings": buildings}, aoi)

    assert result["fsi"] is None
    assert result["fsi_coverage"] == pytest.approx(coverage)
    assert "below" in result["fsi_source"]
    assert "GHSL" not in result["fsi_source"]
