"""Square-dependent summary shared by the building-footprint providers."""

from __future__ import annotations

import numpy as np

from ..types import LayerResult

LOW_HEIGHT_FINDING = "fewer than half of buildings have a known height"


def summarise_building_heights(result: LayerResult) -> LayerResult:
    """Coverage = share of footprints with a finite `height_m` > 0; degraded below half."""
    from dataclasses import replace

    gdf = result.gdf
    n = 0 if gdf is None else len(gdf)
    if n and "height_m" in gdf.columns:
        h = gdf["height_m"].astype(float).to_numpy()
        known = int((np.isfinite(h) & (h > 0)).sum())
    else:
        known = 0
    coverage = known / n if n else 0.0
    low = coverage < 0.5
    return replace(
        result,
        coverage=coverage,
        degraded=low,
        findings=[LOW_HEIGHT_FINDING] if low else [],
    )
