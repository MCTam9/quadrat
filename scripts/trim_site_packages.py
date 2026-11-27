"""Delete files from installed packages that the API never loads, to shrink the Vercel bundle.

Run by the API service's install command (vercel.json) with the same interpreter pip used.
Vercel's `excludeFiles` only applies to project files, not installed packages, so the trimming
has to happen here. Verified on linux/amd64, Python 3.12, with the same install.

pyogrio is deleted outright: geopandas declares it, so pip always installs it, but it only loads
inside `read_file`/`to_file`, which the API never calls (GeoPackages are written by
`sce/export/gpkg_writer.py`; tests/meta guards this). It bundles a second copy of GDAL (~100 MB).
pyarrow is no longer a core dependency, so there is nothing of it to trim.

`--profile site` is for the site function (`api/main.py` on Vercel), which serves everything but
`/api/export`. It also deletes the export-only stack: matplotlib and what only it pulls in, and ezdxf
(a core dependency for the CLI's DXF export; rhino3dm and trimesh are simply not installed). Contours use
contourpy directly, and tests/meta/test_site_api_without_report_stack.py checks that the site
routes never import any of it. The export function (`api/export.py`) keeps the default profile.
"""

from __future__ import annotations

import argparse
import shutil
import sysconfig
from pathlib import Path

SOURCE_SUFFIXES = {".pyx", ".pxd", ".pyi", ".h", ".hpp", ".c", ".cpp"}
# Never imported by the API; see the module docstring.
UNUSED_PACKAGES = ("pyogrio", "pyogrio.libs", "pyogrio-*.dist-info")
# Also deleted for the site function: matplotlib and its own dependencies, which nothing else uses,
# and ezdxf (DXF export only).
# contourpy stays (sce/export/_contours.py); pyparsing, packaging and python-dateutil stay because
# other packages need them.
REPORT_PACKAGES = (
    "matplotlib",
    "matplotlib.libs",
    "matplotlib-*.dist-info",
    "mpl_toolkits",
    "pylab.py",
    "fontTools",
    "fonttools-*.dist-info",
    "PIL",
    "pillow.libs",
    "pillow-*.dist-info",
    "kiwisolver",
    "kiwisolver-*.dist-info",
    "cycler",
    "cycler-*.dist-info",
    "ezdxf",
    "ezdxf-*.dist-info",
)
PROFILES = {"default": UNUSED_PACKAGES, "site": UNUSED_PACKAGES + REPORT_PACKAGES}


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def trim(site: Path, profile: str = "default") -> int:
    """Delete dead weight under `site`; return bytes freed."""
    before = _size(site)
    for pattern in PROFILES[profile]:
        for p in site.glob(pattern):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    for tests in [d for d in site.rglob("tests") if d.is_dir()]:
        shutil.rmtree(tests, ignore_errors=True)
    for f in [f for f in site.rglob("*") if f.is_file() and f.suffix in SOURCE_SUFFIXES]:
        f.unlink(missing_ok=True)
    return before - _size(site)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", nargs="?", type=Path, default=Path(sysconfig.get_paths()["purelib"]))
    parser.add_argument("--profile", choices=sorted(PROFILES), default="default")
    args = parser.parse_args()
    freed = trim(args.site, args.profile)
    print(f"trim_site_packages: profile {args.profile}, freed {freed / 1e6:.0f} MB in {args.site}")
