"""Landuse/landcover metrics: fractions must sum to exactly 1.0.

OSM landuse coverage is routinely partial, so the "unmapped" fraction is the
number that makes the classes an honest partition of the AOI rather than an
undercount that silently vanishes.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from sce.aoi import AOI, NonMetricCRSError
from sce.metrics.landuse import landuse_metrics
from sce.types import LayerResult


def _aoi() -> AOI:
    return AOI.from_point(0.0, 51.0, 50.0, name="landuse")


def test_osm_landuse_fractions_sum_to_one_with_unmapped():
    aoi = _aoi()
    residential = box(-50, -50, -10, 50)
    commercial = box(-10, -50, 10, 50)
    gdf = gpd.GeoDataFrame({"landuse": ["residential", "commercial"]}, geometry=[residential, commercial], crs=aoi.crs)
    layers = {"landuse": LayerResult(layer="landuse", provider="synthetic", gdf=gdf)}
    result = landuse_metrics(layers, aoi)

    assert result["landuse_residential_fraction"] == pytest.approx(0.4)
    assert result["landuse_commercial_fraction"] == pytest.approx(0.2)
    assert result["landuse_unmapped_fraction"] == pytest.approx(0.4)
    total = (
        result["landuse_residential_fraction"]
        + result["landuse_commercial_fraction"]
        + result["landuse_unmapped_fraction"]
    )
    assert total == pytest.approx(1.0)
    assert result["landuse_degraded"] is False


def test_landuse_degraded_flag_below_half_mapped():
    aoi = _aoi()
    tiny = box(-50, -50, -45, -45)
    gdf = gpd.GeoDataFrame({"landuse": ["residential"]}, geometry=[tiny], crs=aoi.crs)
    layers = {"landuse": LayerResult(layer="landuse", provider="synthetic", gdf=gdf)}
    result = landuse_metrics(layers, aoi)
    assert result["landuse_degraded"] is True
    assert result["landuse_unmapped_fraction"] > 0.5


def test_no_landuse_layer_is_fully_unmapped_not_a_crash():
    aoi = _aoi()
    result = landuse_metrics({}, aoi)
    assert result["landuse_unmapped_fraction"] == pytest.approx(1.0)
    assert result["landuse_degraded"] is True


def test_landcover_fractions_sum_to_one():
    aoi = _aoi()
    array = np.array([[10, 10, 20, 20], [20, 30, 30, 30]], dtype=np.int16)
    raster = {"array": array, "crs": aoi.crs, "nodata": None}
    layers = {"landcover": LayerResult(layer="landcover", provider="synthetic", raster=raster)}
    result = landuse_metrics(layers, aoi)

    keys = [k for k in result if k.startswith("landcover_class_")]
    total = sum(result[k] for k in keys)
    assert total == pytest.approx(1.0)
    assert result["landcover_class_20_fraction"] == pytest.approx(3.0 / 8.0)


def test_landcover_ignores_nodata_pixels():
    aoi = _aoi()
    array = np.array([[10, 10, -1], [-1, -1, -1]], dtype=np.int16)
    raster = {"array": array, "crs": aoi.crs, "nodata": -1}
    layers = {"landcover": LayerResult(layer="landcover", provider="synthetic", raster=raster)}
    result = landuse_metrics(layers, aoi)
    assert result["landcover_class_10_fraction"] == pytest.approx(1.0)


def test_geographic_crs_rejected():
    gdf = gpd.GeoDataFrame({"landuse": ["residential"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    layers = {"landuse": LayerResult(layer="landuse", provider="synthetic", gdf=gdf)}
    aoi = _aoi()
    with pytest.raises(NonMetricCRSError):
        landuse_metrics(layers, aoi)


def test_requires_attribute_declared():
    assert landuse_metrics.REQUIRES == ()


def test_overlapping_classes_still_partition_the_site():
    """A park drawn inside a residential zone must not be counted twice.

    OSM tags overlap freely. If per-class areas are summed rather than allocated,
    the stacked bar on the sheet runs past 100% of a site, which is the kind of
    error a GIS reader spots instantly.
    """
    import geopandas as gpd
    from shapely.geometry import box

    from sce.aoi import AOI
    from sce.metrics.landuse import landuse_metrics
    from sce.types import LayerResult

    aoi = AOI.from_point(3.0, 40.0, 500.0, name="overlap")
    minx, miny, maxx, maxy = aoi.bounds_metric
    # Residential covers the whole site; a park covers a quarter of it, inside.
    residential = box(minx, miny, maxx, maxy)
    park = box(minx, miny, minx + (maxx - minx) / 2, miny + (maxy - miny) / 2)
    gdf = gpd.GeoDataFrame(
        {"class": ["residential", "green_space"], "geometry": [residential, park]},
        crs=aoi.crs,
    )
    out = landuse_metrics({"landuse": LayerResult("landuse", "test", gdf=gdf)}, aoi)

    shares = {k: v for k, v in out.items() if k.startswith("landuse_") and k.endswith("_fraction")}
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-6)
    assert out["landuse_green_space_fraction"] == pytest.approx(0.25, abs=1e-3)
    assert out["landuse_residential_fraction"] == pytest.approx(0.75, abs=1e-3)
    assert out["landuse_unmapped_fraction"] == pytest.approx(0.0, abs=1e-6)
