"""Data-sufficiency judgement over a fetched set of LayerResult objects.

Dependency-free logic: no network, no geometry math beyond what a LayerResult
already carries (`coverage`, `degraded`, feature counts). Produces the
per-layer coverage summary, an overall `degraded` flag, and the human-readable
warning strings the report sheet prints under the title block — the "same
command, richer where richer data exists" honesty check.
"""

from __future__ import annotations

from typing import Any

from .types import LayerResult

# Below this fraction a layer's own self-reported coverage is called out by
# name in a warning, not just folded into the degraded flag.
LOW_COVERAGE_THRESHOLD = 0.5

# Layers with no result at all are expected to sometimes be missing (e.g.
# constraints outside GB); these do not count as a data problem worth a loud
# warning, only a quiet coverage=None entry.
OPTIONAL_LAYERS = {"constraints"}


def assess(layers: dict[str, LayerResult | None], aoi) -> dict[str, Any]:
    """Judge sufficiency of a fetched layer set for one AOI.

    Returns `{"coverage": {layer: 0..1|None}, "degraded": bool, "warnings": [str]}`.
    """
    coverage: dict[str, float | None] = {}
    warnings: list[str] = []
    degraded = False

    for layer, result in layers.items():
        if result is None:
            coverage[layer] = None
            if layer not in OPTIONAL_LAYERS:
                degraded = True
                warnings.append(f"{layer}: no provider returned data for this AOI.")
            continue

        coverage[layer] = result.coverage

        if result.degraded:
            degraded = True

        if result.coverage is not None and result.coverage < LOW_COVERAGE_THRESHOLD:
            degraded = True
            warnings.append(
                f"{layer}: only {result.coverage:.0%} coverage from {result.provider}; "
                "treat derived numbers as indicative, not precise."
            )

        if result.gdf is not None and result.raster is None and len(result.gdf) == 0:
            degraded = True
            warnings.append(f"{layer}: {result.provider} returned zero features for this AOI.")

        warnings.extend(f"{layer}: {note}" for note in result.notes if "fell back after" in note)

    if layers.get("landcover") is not None and layers.get("landuse") is None:
        warnings.append(
            "landuse: no OSM landuse coverage for this AOI; land cover shown from ESA WorldCover instead."
        )
    elif _low_osm_landuse(layers.get("landuse")):
        pct = layers["landuse"].coverage or 0.0
        warnings.append(
            f"OSM landuse covers {pct:.0%} of this AOI; "
            "land cover shown from ESA WorldCover where gaps exist."
        )

    return {"coverage": coverage, "degraded": degraded, "warnings": warnings}


def _low_osm_landuse(landuse: LayerResult | None) -> bool:
    return landuse is not None and landuse.coverage is not None and landuse.coverage < LOW_COVERAGE_THRESHOLD
