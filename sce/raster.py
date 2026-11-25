"""A raster that knows the true-north square it describes.

AOI squares are aligned to TRUE north, so in a projected CRS they sit rotated
by the grid convergence inside their (north-up) bounding box. A raster grid
covers that bounding box; the corner cells belong to the neighbours. Every
area-based figure (coverage, means, class fractions) must therefore be taken
over the cells inside the square, never over the whole array. `SiteRaster`
carries the square next to the grid so the mask cannot be forgotten, and holds
the one rule for what counts as "no data" (NaN, a sentinel value, or 0).

Nodata rules, in one place:
  * `nodata=None`: float cells are invalid when NaN; integer cells are all valid.
  * `nodata=nan`: same as None for floats.
  * `nodata=<number>`: cells equal to it are invalid, and NaN cells too when float.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from affine import Affine

from .aoi import AOI


def inside_mask(shape: tuple[int, int], transform: Affine, square: Any) -> np.ndarray:
    """True for cells whose centre lies inside `square.geometry` (the true-north square)."""
    from rasterio.features import geometry_mask

    return geometry_mask([square.geometry], out_shape=shape, transform=transform, invert=True)


@dataclass(frozen=True, eq=False)
class SiteRaster:
    """A north-up, square-cell grid in a metric CRS, plus the square it describes."""

    array: np.ndarray
    transform: Affine
    crs: Any
    square: AOI
    nodata: float | int | None = None
    kind: str = ""
    _inside: np.ndarray | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_array(
        cls,
        array: np.ndarray,
        transform: Affine,
        crs: Any,
        *,
        square: AOI,
        nodata: float | int | None = None,
        kind: str = "",
        blank_outside: bool = False,
    ) -> SiteRaster:
        """Wrap a grid. With `blank_outside`, cells outside the square are set to nodata."""
        raster = cls(np.asarray(array), transform, crs, square, nodata, kind)
        if blank_outside:
            raster = raster._blanked()
        return raster

    # -- grid access --------------------------------------------------------

    @property
    def res(self) -> tuple[float, float]:
        return (abs(self.transform.a), abs(self.transform.e))

    @property
    def shape(self) -> tuple[int, int]:
        return self.array.shape[:2]

    def float_array(self) -> np.ndarray:
        """The grid as float64 with every invalid cell (see module docstring) set to NaN."""
        arr = np.asarray(self.array, dtype=float)
        if self.nodata is not None and not np.isnan(self.nodata):
            arr = np.where(arr == self.nodata, np.nan, arr)
        return arr

    # -- the square ---------------------------------------------------------

    def inside(self) -> np.ndarray:
        """Boolean grid, True for cells whose centre is inside the square. Computed once."""
        if self._inside is None:
            object.__setattr__(self, "_inside", inside_mask(self.shape, self.transform, self.square))
        return self._inside

    @property
    def n_inside(self) -> int:
        return int(self.inside().sum())

    def _valid(self) -> np.ndarray:
        """Cells with real data, anywhere in the grid."""
        arr = self.array
        valid = np.ones(arr.shape, dtype=bool)
        if np.issubdtype(arr.dtype, np.floating):
            valid &= ~np.isnan(arr)
        if self.nodata is not None and not np.isnan(self.nodata):
            valid &= arr != self.nodata
        return valid

    def values_inside(self, valid: Callable[[np.ndarray], np.ndarray] | None = None) -> np.ndarray:
        """1D values of the cells inside the square that hold data.

        `valid` is an optional predicate over the values (e.g. `lambda v: v > 2.5`)
        that narrows the selection further.
        """
        values = self.array[self._valid() & self.inside()]
        if valid is not None:
            values = values[valid(values)]
        return values

    def share_known(self) -> float:
        """Fraction (0..1) of the cells inside the square that hold data: the coverage figure."""
        n = self.n_inside
        if not n:
            return 0.0
        return int((self._valid() & self.inside()).sum()) / n

    # -- derived rasters ----------------------------------------------------

    def _fill_value(self) -> float | int:
        if np.issubdtype(self.array.dtype, np.floating):
            return np.nan
        return 0 if self.nodata is None or not np.isfinite(self.nodata) else self.nodata

    def _blanked(self) -> SiteRaster:
        arr = self.array.copy()
        arr[~self.inside()] = self._fill_value()
        return replace(self, array=arr)

    def window(self, square: AOI) -> SiteRaster:
        """Clip to `square`'s bounding box and blank the cells outside the square itself."""
        t = self.transform
        res_x, res_y = t.a, -t.e
        minx, miny, maxx, maxy = square.bounds_metric
        rows, cols = self.shape
        col0 = max(0, math.floor((minx - t.c) / res_x))
        col1 = min(cols, math.ceil((maxx - t.c) / res_x))
        row0 = max(0, math.floor((t.f - maxy) / res_y))
        row1 = min(rows, math.ceil((t.f - miny) / res_y))
        new_t = Affine(t.a, t.b, t.c + col0 * res_x, t.d, t.e, t.f - row0 * res_y)
        window = self.array[row0:row1, col0:col1].copy()
        return replace(self, array=window, transform=new_t, square=square)._blanked()
