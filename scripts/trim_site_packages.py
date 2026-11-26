"""Delete files from installed packages that the API never loads, to shrink the Vercel bundle.

Run by the API service's install command (vercel.json) with the same interpreter pip used.
Vercel's `excludeFiles` only applies to project files, not installed packages, so the trimming
has to happen here. Verified on linux/amd64, Python 3.12, with the same install.

pyogrio is deleted outright: geopandas declares it, so pip always installs it, but it only loads
inside `read_file`/`to_file`, which the API never calls (GeoPackages are written by
`sce/export/gpkg_writer.py`; tests/meta guards this). It bundles a second copy of GDAL (~100 MB).
pyarrow is no longer a core dependency, so there is nothing of it to trim.
"""

from __future__ import annotations

import shutil
import sys
import sysconfig
from pathlib import Path

SOURCE_SUFFIXES = {".pyx", ".pxd", ".pyi", ".h", ".hpp", ".c", ".cpp"}
# Never imported by the API; see the module docstring.
UNUSED_PACKAGES = ("pyogrio", "pyogrio.libs", "pyogrio-*.dist-info")


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def trim(site: Path) -> int:
    """Delete dead weight under `site`; return bytes freed."""
    before = _size(site)
    for pattern in UNUSED_PACKAGES:
        for p in site.glob(pattern):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    for tests in [d for d in site.rglob("tests") if d.is_dir()]:
        shutil.rmtree(tests, ignore_errors=True)
    for f in [f for f in site.rglob("*") if f.is_file() and f.suffix in SOURCE_SUFFIXES]:
        f.unlink(missing_ok=True)
    return before - _size(site)


if __name__ == "__main__":
    site = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(sysconfig.get_paths()["purelib"])
    freed = trim(site)
    print(f"trim_site_packages: freed {freed / 1e6:.0f} MB in {site}")
