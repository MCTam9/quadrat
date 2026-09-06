"""Shared types. The contract every provider and metric is written against."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import geopandas as gpd


@dataclass
class Source:
    """One retrieval, recorded for the title block and dossier.json."""

    name: str
    url: str
    licence: str
    retrieved: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    note: str = ""
    licence_url: str = ""
    commercial_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "retrieved": self.retrieved,
            "commercial_ok": self.commercial_ok,
            "note": self.note,
        }


@dataclass
class LayerResult:
    """What every provider returns.

    `gdf` is ALWAYS already in the AOI metric CRS. `raster` carries array plus
    transform for terrain and land-cover providers. `coverage` is 0..1 where the
    provider can judge its own completeness, else None.
    """

    layer: str
    provider: str
    gdf: gpd.GeoDataFrame | None = None
    raster: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    sources: list[Source] = field(default_factory=list)
    coverage: float | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        if self.raster is not None or self.data is not None:
            return False
        return self.gdf is None or len(self.gdf) == 0

    def provenance(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "provider": self.provider,
            "features": 0 if self.gdf is None else int(len(self.gdf)),
            "coverage": self.coverage,
            "degraded": self.degraded,
            "sources": [s.to_dict() for s in self.sources],
            "notes": self.notes,
        }


class Provider:
    """Base class. Subclasses declare name/layer/licence/rank.

    `rank` orders the chain for a layer: lower runs first. A provider that
    returns an empty result, or raises, falls through to the next one.
    """

    name: str = ""
    layer: str = ""
    licence: str = ""
    rank: int = 100
    commercial_ok: bool = True

    def available(self, aoi) -> bool:  # noqa: ANN001
        """True when this provider can serve this AOI (e.g. inside GB only)."""
        return True

    def fetch(self, aoi, cache) -> LayerResult:  # noqa: ANN001
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} layer={self.layer!r} rank={self.rank}>"
