"""Every provider anyone registers must obey the shape in CONTRACT.md.

Runs against whatever is registered at import time of `sce.providers`. Skips
cleanly while that package is still empty or partially written.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sce.providers")

# The layer vocabulary is defined once, in sce.cli, because the CLI has to
# offer it as a choice anyway. Copying it here would mean a new layer passes its
# own test while the command that fetches it has never heard of it.
from sce.cli import LAYERS as _LAYER_TUPLE
from sce.registry import REGISTRY
from sce.types import Provider

LAYERS = set(_LAYER_TUPLE)


def test_the_layer_vocabulary_is_documented():
    """CONTRACT.md is what the next provider author reads. A layer the code
    accepts but the contract never names is a layer nobody knows exists."""
    from pathlib import Path

    contract = Path(__file__).resolve().parents[2] / "CONTRACT.md"
    text = contract.read_text()
    undocumented = sorted(layer for layer in LAYERS if f"`{layer}`" not in text)
    assert not undocumented, f"layers missing from CONTRACT.md: {undocumented}"


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
        assert cls.available is not Provider.available, f"{cls.__name__} does not override available()"
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


def test_every_provider_module_is_imported_by_the_package():
    """A provider module that nobody imports registers nothing.

    That failure is silent: the layer simply never appears, and the sheet prints
    an empty panel instead of raising. This test is the only thing standing
    between that and a demo with three blank boxes on it.
    """
    import pkgutil
    from pathlib import Path

    import sce.providers as pkg

    on_disk = {
        m.name for m in pkgutil.iter_modules([str(Path(pkg.__file__).parent)]) if not m.name.startswith("_")
    }
    imported = {name for name in on_disk if hasattr(pkg, name)}
    missing = sorted(on_disk - imported)
    assert not missing, (
        f"provider modules not imported in sce/providers/__init__.py: {missing}. "
        "They are registering nothing."
    )
