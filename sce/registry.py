"""Layer -> ordered provider chain, with fallback and override."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable

from .types import LayerResult, Provider

log = logging.getLogger("sce.registry")


class Registry:
    def __init__(self) -> None:
        self._by_layer: dict[str, list[Provider]] = defaultdict(list)

    def register(self, provider: Provider) -> Provider:
        if not provider.name or not provider.layer:
            raise ValueError(f"provider {provider!r} must declare name and layer")
        self._by_layer[provider.layer].append(provider)
        self._by_layer[provider.layer].sort(key=lambda p: p.rank)
        return provider

    def layers(self) -> list[str]:
        return sorted(self._by_layer)

    def providers(self, layer: str | None = None) -> list[Provider]:
        if layer is None:
            return [p for ps in self._by_layer.values() for p in ps]
        return list(self._by_layer.get(layer, []))

    def chain(self, layer: str, aoi) -> list[Provider]:
        return [p for p in self._by_layer.get(layer, []) if p.available(aoi)]

    def fetch(
        self,
        layer: str,
        aoi,
        cache,
        *,
        override: str | None = None,
        allow_non_commercial: bool = False,
    ) -> LayerResult | None:
        """Walk the chain until one provider returns a non-empty result."""
        chain: Iterable[Provider] = self.chain(layer, aoi)
        if override:
            chain = [p for p in chain if p.name == override]
            if not chain:
                raise ValueError(f"no provider named {override!r} available for layer {layer!r}")
        tried: list[str] = []
        for provider in chain:
            if not provider.commercial_ok and not allow_non_commercial:
                log.info("skipping %s (non-commercial licence, not opted in)", provider.name)
                continue
            try:
                result = provider.fetch(aoi, cache)
            except Exception as exc:
                log.warning("provider %s failed for %s: %s", provider.name, layer, exc)
                tried.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue
            if result is None or result.is_empty:
                log.info("provider %s returned nothing for %s", provider.name, layer)
                tried.append(f"{provider.name}: empty")
                continue
            if tried:
                result.notes.append("fell back after: " + "; ".join(tried))
            return result
        log.warning("no provider produced %s (tried: %s)", layer, tried or "none available")
        return None


REGISTRY = Registry()
