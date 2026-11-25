"""SiteRaster: the grid plus the true-north square it describes."""

from __future__ import annotations

import math

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Point

from sce.aoi import AOI
from sce.providers.height_ea_lidar import BUILDING_LIKE_MIN_M, EaLidarBuildingHeightProvider
from sce.raster import SiteRaster
from sce.types import LayerResult

RES = 10.0


@pytest.fixture
def outer() -> AOI:
    # Offset from the UTM central meridian, so the square is visibly rotated in the grid.
    return AOI.from_point(-4.0, 55.0, 600.0, name="outer")


@pytest.fixture
def inner(outer: AOI) -> AOI:
    return AOI.from_point(-4.0, 55.0, 200.0, name="inner", crs=outer.crs)


def _grid(aoi: AOI, res: float = RES) -> tuple[Affine, tuple[int, int]]:
    minx, miny, maxx, maxy = aoi.bounds_metric
    shape = (math.ceil((maxy - miny) / res), math.ceil((maxx - minx) / res))
    return Affine(res, 0, minx, 0, -res, maxy), shape


def _centres(t: Affine, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.indices(shape)
    return t.c + (cols + 0.5) * t.a, t.f + (rows + 0.5) * t.e


def test_inside_matches_true_north_square_not_the_bbox(outer):
    t, shape = _grid(outer)
    r = SiteRaster.from_array(np.full(shape, 5.0), t, outer.crs, square=outer)
    inside = r.inside()
    assert inside.shape == r.array.shape
    assert 0 < inside.sum() < inside.size  # corners of the bbox are excluded
    xs, ys = _centres(t, shape)
    pts = zip(xs.ravel(), ys.ravel(), strict=True)
    expected = np.array([outer.geometry.contains(Point(x, y)) for x, y in pts]).reshape(shape)
    assert (expected == inside).mean() > 0.999
    assert not inside[0, 0] and not inside[-1, -1]
    assert inside[shape[0] // 2, shape[1] // 2]
    assert r.inside() is inside  # cached


def test_share_known_counts_only_inside_cells(outer):
    t, shape = _grid(outer)
    arr = np.full(shape, 3.0)
    full = SiteRaster.from_array(arr, t, outer.crs, square=outer, nodata=float("nan"), blank_outside=True)
    # Blanked bbox corners are neither known nor unknown: they do not lower coverage.
    assert full.share_known() == pytest.approx(1.0)
    arr = full.array.copy()
    arr[: shape[0] // 2] = np.nan  # north half unknown
    half = SiteRaster.from_array(arr, t, outer.crs, square=outer, nodata=float("nan"))
    assert half.share_known() == pytest.approx(0.5, abs=0.05)


def test_values_inside_drops_nodata_nan_and_applies_predicate(outer):
    t, shape = _grid(outer)
    arr = np.full(shape, 1.0)
    arr[0, 0] = 99.0  # outside the square: must not appear
    c = (shape[0] // 2, shape[1] // 2)
    arr[c] = 10.0
    arr[c[0], c[1] + 1] = np.nan
    r = SiteRaster.from_array(arr, t, outer.crs, square=outer, nodata=float("nan"))
    v = r.values_inside()
    assert 99.0 not in v and not np.isnan(v).any()
    assert v.size == r.n_inside - 1
    assert r.values_inside(lambda x: x > 2.5).tolist() == [10.0]


def test_nodata_as_nan_and_as_sentinel_agree(outer):
    t, shape = _grid(outer)
    base = np.full(shape, 7.0)
    base[: shape[0] // 4] = np.nan
    as_nan = SiteRaster.from_array(base, t, outer.crs, square=outer, nodata=float("nan"))
    sentinel = np.where(np.isnan(base), -9999.0, base)
    as_sentinel = SiteRaster.from_array(sentinel, t, outer.crs, square=outer, nodata=-9999.0)
    assert as_nan.share_known() == pytest.approx(as_sentinel.share_known())
    assert as_nan.values_inside().sum() == pytest.approx(as_sentinel.values_inside().sum())
    assert np.array_equal(np.isnan(as_nan.float_array()), np.isnan(as_sentinel.float_array()))


def test_integer_zero_nodata_and_no_nodata(outer):
    t, shape = _grid(outer)
    classes = np.full(shape, 50, dtype=np.uint8)
    classes[:, : shape[1] // 2] = 0
    r = SiteRaster.from_array(classes, t, outer.crs, square=outer, nodata=0)
    assert set(r.values_inside().tolist()) == {50}
    assert r.share_known() == pytest.approx(0.5, abs=0.05)
    no_nodata = SiteRaster.from_array(classes, t, outer.crs, square=outer)  # 0 is a class here
    assert no_nodata.share_known() == pytest.approx(1.0)


def test_blank_outside_and_res(outer):
    t, shape = _grid(outer)
    r = SiteRaster.from_array(
        np.ones(shape), t, outer.crs, square=outer, nodata=float("nan"), blank_outside=True
    )
    assert np.isnan(r.array[~r.inside()]).all() and np.isfinite(r.array[r.inside()]).all()
    assert r.res == (RES, RES)


def test_window_keeps_outer_cells_and_masks_for_the_new_square(outer, inner):
    t, shape = _grid(outer)
    xs, ys = _centres(t, shape)
    big = SiteRaster.from_array(xs / 50.0 + ys / 100.0, t, outer.crs, square=outer, nodata=float("nan"))
    win = big.window(inner)

    assert win.square is inner
    assert win.array.shape[0] < shape[0]
    assert win.share_known() == pytest.approx(1.0)  # corners blanked, not counted as missing
    assert np.isnan(win.array[~win.inside()]).all()
    col0 = round((win.transform.c - t.c) / RES)
    row0 = round((t.f - win.transform.f) / RES)
    sub = big.array[row0 : row0 + win.array.shape[0], col0 : col0 + win.array.shape[1]]
    assert np.array_equal(win.array[win.inside()], sub[win.inside()])


def test_window_summary_matches_raster_built_on_the_smaller_square(outer, inner):
    p = EaLidarBuildingHeightProvider()
    cx = inner.geometry.centroid.x

    def build(aoi: AOI) -> LayerResult:
        t, shape = _grid(aoi)
        xs, _ = _centres(t, shape)
        arr = np.where(xs > cx, 12.0, 1.0)  # a 12 m block east of the centre on 1 m ground
        raster = SiteRaster.from_array(
            arr, t, aoi.crs, square=aoi, nodata=float("nan"), kind="ndsm", blank_outside=True
        )
        return LayerResult("building_height", p.name, raster=raster, data={"kind": "ndsm"})

    windowed = p.summarise(
        LayerResult("building_height", p.name, raster=build(outer).raster.window(inner)), inner
    )
    direct = p.summarise(build(inner), inner)
    assert BUILDING_LIKE_MIN_M == 2.5
    assert windowed.data["mean_height_m"] == pytest.approx(direct.data["mean_height_m"])
    assert windowed.data["mean_height_m"] == pytest.approx(12.0)
    assert windowed.coverage == pytest.approx(direct.coverage) == pytest.approx(1.0)
