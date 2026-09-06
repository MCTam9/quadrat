"""Repo-wide conventions, checked with `ast` so half-written modules still parse.

Deliberately avoids importing `sce.*` submodules: other agents are actively
writing sce/providers, sce/metrics, sce/export and sce/report, and an import
error in one half-finished module must not take this test down with it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCE_ROOT = Path(__file__).parent.parent.parent / "sce"

BANNED_IMPORTS = {"fiona", "conda"}


def _sce_py_files() -> list[Path]:
    return sorted(p for p in SCE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


@pytest.fixture(scope="module")
def sce_files():
    files = _sce_py_files()
    if not files:
        pytest.skip("sce/ has no python files")
    return files


@pytest.mark.parametrize("path", _sce_py_files(), ids=lambda p: str(p.relative_to(SCE_ROOT)))
def test_module_has_docstring(path: Path):
    if not path.read_text().strip():
        pytest.skip(f"{path.relative_to(SCE_ROOT)} is an empty placeholder, not yet written")
    tree = _parse(path)
    assert ast.get_docstring(tree), f"{path.relative_to(SCE_ROOT)} has no module docstring"


@pytest.mark.parametrize("path", _sce_py_files(), ids=lambda p: str(p.relative_to(SCE_ROOT)))
def test_module_does_not_import_banned_packages(path: Path):
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in BANNED_IMPORTS, (
                    f"{path.relative_to(SCE_ROOT)} imports banned package {root!r}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in BANNED_IMPORTS, f"{path.relative_to(SCE_ROOT)} imports banned package {root!r}"


def _is_public_function(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    # Dunder/magic methods and simple properties/overrides are exempt; the
    # contract cares about the module's own public surface, not every method.
    return not node.name.startswith("_")


def _iter_top_level_and_method_functions(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield sub


def _has_any_param_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    positional = [a for a in (args.posonlyargs + args.args) if a.arg not in {"self", "cls"}]
    all_args = positional + args.kwonlyargs
    if args.vararg:
        all_args.append(args.vararg)
    if args.kwarg:
        all_args.append(args.kwarg)
    return any(a.annotation is not None for a in all_args)


_DECORATOR_EXEMPT = {"overload", "property", "setter"}


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for dec in node.decorator_list:
        target = dec
        if isinstance(target, ast.Call):
            target = target.func
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


@pytest.mark.parametrize("path", _sce_py_files(), ids=lambda p: str(p.relative_to(SCE_ROOT)))
def test_public_functions_have_return_annotations(path: Path):
    tree = _parse(path)
    offenders = []
    for node in _iter_top_level_and_method_functions(tree):
        if not _is_public_function(node):
            continue
        if node.name in {"__init__", "__post_init__"}:
            continue
        if _decorator_names(node) & _DECORATOR_EXEMPT:
            continue
        if node.returns is not None:
            continue
        if node.args.args and not _has_any_param_annotation(node) and len(node.args.args) > 1:
            # A function whose non-self parameters are all unannotated predates
            # strict typing in this file (e.g. AOI.to_metric(self, gdf)); flag
            # only functions that have started annotating but stopped short.
            continue
        offenders.append(f"{node.name} (line {node.lineno})")
    assert not offenders, (
        f"{path.relative_to(SCE_ROOT)}: public functions missing return annotations: {offenders}"
    )
