"""Shared types. The contract every provider and metric is written against."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import geopandas as gpd

from .raster import SiteRaster


@dataclass
class Source:
    """One retrieval, recorded for the title block and dossier.json."""

    name: str
    url: str
    licence: str
    retrieved: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
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

    `gdf` is ALWAYS already in the AOI metric CRS. `raster` is a `SiteRaster` (grid plus the
    square it describes) for terrain, land-cover and height providers. `coverage` is 0..1 where the
    provider can judge its own completeness, else None.
    """

    layer: str
    provider: str
    gdf: gpd.GeoDataFrame | None = None
    raster: SiteRaster | None = None
    data: dict[str, Any] | None = None
    sources: list[Source] = field(default_factory=list)
    coverage: float | None = None
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    # Notes that depend on the square the result covers (e.g. low-coverage
    # statements). Always recomputed by `Provider.summarise`; `notes` holds the
    # square-independent facts (licence caveats, fallbacks, DSM-not-DTM).
    findings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        if self.raster is not None or self.data is not None:
            return False
        return self.gdf is None or len(self.gdf) == 0

    def provenance(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "provider": self.provider,
            "features": 0 if self.gdf is None else len(self.gdf),
            "coverage": self.coverage,
            "degraded": self.degraded,
            "sources": [s.to_dict() for s in self.sources],
            "notes": [*self.notes, *self.findings],
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
    # Credit line some data licences require next to the name (e.g. OpenMapTiles).
    # Written into ATTRIBUTION.md beside the provider.
    credit: str = ""

    def available(self, aoi) -> bool:
        """True when this provider can serve this AOI (e.g. inside GB only)."""
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        raise NotImplementedError

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        """Recompute the square-dependent summary of `result` for `aoi`.

        `result`'s geometry or raster must already be confined to `aoi`. Returns
        a copy with `coverage`, `degraded`, `findings` and any square-dependent
        `data` (means, fractions, summaries) recomputed for that square. Pure:
        no I/O, and `result` is not mutated. `fetch` ends by calling this, and
        `sce.clip` calls it after cutting geometry, so one rule serves both.
        The default returns `result` unchanged.
        """
        return result

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} layer={self.layer!r} rank={self.rank}>"
