"""pyarrow is an optional extra, so the Overture provider must register only when it is there."""

from __future__ import annotations

import importlib.util

import pytest

from sce.providers import overture_buildings
from sce.registry import Registry


def test_registry_builds_without_pyarrow(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: None if name == "pyarrow" else real(name, *a, **k)
    )
    registry = Registry()
    overture_buildings.register(registry)
    assert registry.provider("overture_buildings") is None


def test_no_module_level_pyarrow_import():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(overture_buildings))
    for node in tree.body:
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        assert not any(n.split(".")[0] == "pyarrow" for n in names)


def test_registers_when_pyarrow_present():
    pytest.importorskip("pyarrow")
    registry = Registry()
    overture_buildings.register(registry)
    assert registry.provider("overture_buildings") is not None
