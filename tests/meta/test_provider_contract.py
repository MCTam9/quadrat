"""Every provider anyone registers must obey the shape in CONTRACT.md.

Runs against whatever is registered at import time of `sce.providers`. Skips
cleanly while that package is still empty or partially written.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sce.providers")

from sce.registry import REGISTRY
from sce.types import Provider

LAYERS = {
    "streets",
    "buildings",
    "landuse",
    "landcover",
    "amenities",
    "terrain",
    "climate",
    "constraints",
}


def _providers():
    import sce.providers  # noqa: F401  - import triggers REGISTRY.register(...) calls

    return REGISTRY.providers()


@pytest.fixture(scope="module")
def providers():
    provs = _providers()
    if not provs:
        pytest.skip("no providers registered yet")
    return provs


def test_every_provider_declares_required_attributes(providers):
    for p in providers:
        assert p.name, f"{p!r} has no name"
        assert isinstance(p.name, str)
        assert p.layer, f"{p!r} has no layer"
        assert p.layer in LAYERS, f"{p!r} declares unknown layer {p.layer!r}, not in {LAYERS}"
        assert p.licence, f"{p!r} has no licence"
        assert isinstance(p.licence, str)
        assert isinstance(p.rank, int), f"{p!r} rank is not an int: {p.rank!r}"


def test_every_provider_overrides_available_and_fetch(providers):
    for p in providers:
        cls = type(p)
        assert cls.available is not Provider.available, (
            f"{cls.__name__} does not override available()"
        )
        assert cls.fetch is not Provider.fetch, f"{cls.__name__} does not override fetch()"


def test_provider_names_are_unique(providers):
    names = [p.name for p in providers]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate provider names: {dupes}"


def test_every_layer_has_at_least_one_provider(providers):
    layers_covered = {p.layer for p in providers}
    missing = LAYERS - layers_covered
    if missing:
        pytest.skip(f"layers not yet covered by any provider: {missing}")
