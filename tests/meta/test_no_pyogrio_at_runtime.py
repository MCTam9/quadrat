"""The API bundle deletes pyogrio (scripts/trim_site_packages.py), so nothing it runs may touch it.

geopandas imports pyogrio only inside `read_file`/`to_file`, so those calls are what to ban in
`sce/` and `api/`. Tests are exempt: dev installs keep pyogrio and use it to validate our files.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
FILES = sorted(p for d in ("sce", "api") for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts)
BANNED_CALLS = {"to_file", "read_file"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_module_does_not_use_pyogrio(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "pyogrio" for a in node.names), "imports pyogrio"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "pyogrio", "imports pyogrio"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in BANNED_CALLS, f"calls .{node.func.attr}( (needs pyogrio)"
