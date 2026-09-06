"""Importing this package registers every built-in provider with REGISTRY.

Every provider module must be listed here. `tests/meta/test_provider_contract.py`
asserts that this list matches the directory, because a provider that exists but
is never imported registers nothing and fails silently as an empty panel on the
sheet rather than as an error.
"""

from __future__ import annotations

from . import (  # noqa: F401
    climate_openmeteo,
    landcover_worldcover,
    osm_amenities,
    osm_buildings,
    osm_landuse,
    osm_streets,
    overture_buildings,
    terrain_copernicus,
    uk_constraints,
)
