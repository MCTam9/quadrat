"""The report pipeline as plain functions, shared by the CLI and the web API.

`cli.py` used to own this sequence privately. The web backend needs the same
steps without click, so they live here and the CLI is now a thin shell that
prints progress.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .aoi import AOI
from .types import LayerResult

LAYERS = (
    "streets",
    "buildings",
    "landuse",
    "landcover",
    "amenities",
    "terrain",
    "climate",
    "constraints",
    "building_height",
)

# The web app loads everything but climate up front; climate is fetched when asked for.
SITE_LAYERS = tuple(layer for layer in LAYERS if layer != "climate")

LayerCallback = Callable[[str, LayerResult | None], None]


def build_aoi(coords: str | None, geojson: str | None, radius: float, name: str) -> AOI:
    """AOI from `'lon,lat'` + half-width, or from a WGS84 GeoJSON file path.

    Raises ValueError with a user-facing message on malformed input.
    """
    if geojson:
        obj = json.loads(Path(geojson).read_text())
        return AOI.from_geojson(obj, name=name)
    if not coords:
        raise ValueError("give --coords 'lon,lat' or --geojson path")
    try:
        lon_s, lat_s = coords.split(",")
        lon, lat = float(lon_s), float(lat_s)
    except ValueError as exc:
        raise ValueError("--coords must be 'lon,lat' in decimal degrees") from exc
    return AOI.from_point(lon, lat, radius, name=name)


# These go through osmnx, whose settings (endpoint, cache folder) are process
# globals. Streets is its own Overpass query; buildings, landuse and amenities
# share one (see `sce/providers/_overpass.py shared_features`), so the feature
# layers run one after another in a single worker and hit that query once.
# `with_overpass_fallback` serialises the settings changes behind a lock, so the
# two groups can run side by side. Everything else is independent HTTP/tile I/O.
OSM_FEATURE_LAYERS = ("buildings", "landuse", "amenities")
OSM_GROUPS: tuple[tuple[str, ...], ...] = (("streets",), OSM_FEATURE_LAYERS)


def fetch_layers(
    aoi: AOI,
    cache: Any,
    only: Iterable[str] | None = None,
    override: dict[str, str] | None = None,
    allow_nc: bool = False,
    on_layer: LayerCallback | None = None,
    *,
    parallel: bool = True,
    timings: dict[str, int] | None = None,
    height_focus: AOI | None = None,
) -> dict[str, LayerResult]:
    """Run every provider chain for the wanted layers.

    `on_layer(name, result_or_None)` fires after each layer so callers can
    report progress (the CLI prints, the API streams). With `parallel`, it may
    fire from worker threads and in completion order rather than LAYERS order;
    the returned dict is always in LAYERS order.

    `timings`, when given, is filled with milliseconds per layer (plus
    `heights` for the LiDAR enrichment). `height_focus`, a smaller AOI in the
    same CRS, is what the `building_height` layer is fetched for: LiDAR tiles
    are the slowest request, and only the requested square and its context ring
    need heights.
    """
    import sce.providers  # noqa: F401  - registers providers

    from .registry import REGISTRY

    override = override or {}
    wanted = [layer for layer in (list(only) if only else list(LAYERS)) if REGISTRY.chain(layer, aoi)]
    results: dict[str, LayerResult | None] = {}

    def one(layer: str) -> None:
        started = time.perf_counter()
        result = REGISTRY.fetch(
            layer,
            height_focus if layer == "building_height" and height_focus is not None else aoi,
            cache,
            override=override.get(layer),
            allow_non_commercial=allow_nc,
        )
        results[layer] = result
        if timings is not None:
            timings[layer] = round((time.perf_counter() - started) * 1000)
        if on_layer is not None:
            on_layer(layer, result)

    if parallel:
        from concurrent.futures import ThreadPoolExecutor

        osm = {layer for group in OSM_GROUPS for layer in group}
        groups = [[layer for layer in group if layer in wanted] for group in OSM_GROUPS]
        groups = [g for g in groups if g]
        independent = [layer for layer in wanted if layer not in osm]

        def run_group(group: list[str]) -> None:
            first: Exception | None = None
            for layer in group:
                try:
                    one(layer)
                except Exception as exc:
                    first = first or exc
            if first is not None:
                raise first

        with ThreadPoolExecutor(max_workers=len(groups) + len(independent)) as pool:
            futures = [pool.submit(run_group, g) for g in groups]
            futures += [pool.submit(one, layer) for layer in independent]
            for f in futures:
                f.result()
    else:
        for layer in wanted:
            one(layer)

    layers = {layer: results[layer] for layer in wanted if results.get(layer) is not None}
    # Where a per-building-resolution height raster exists (EA LiDAR in England),
    # measure the buildings OSM left without a height. A no-op elsewhere.
    from .heights import enrich_building_heights

    started = time.perf_counter()
    enriched = enrich_building_heights(layers)
    if timings is not None:
        timings["heights"] = round((time.perf_counter() - started) * 1000)
    return enriched


def _gpkg(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.gpkg import write_gpkg
    from .export.qml import write_qml_styles

    p = write_gpkg(out / f"{name}.gpkg", layers, aoi, metrics)
    styles = write_qml_styles(p, layers)
    return [p, *styles]


def _dxf(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.dxf import write_dxf

    return [write_dxf(out / f"{name}.dxf", layers, aoi)]


def _3dm(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.rhino import write_3dm

    return [write_3dm(out / f"{name}.3dm", layers, aoi)]


def _png(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .report.sheet import render_sheet

    return [render_sheet(out / f"{name}.png", aoi, layers, metrics, None)]


def _geojson(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.geojson import write_geojson

    return [write_geojson(out / f"{name}.geojson", layers, aoi)]


def _svg(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.svg import write_svg

    return [write_svg(out / f"{name}.svg", layers, aoi)]


def _glb(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.mesh import write_glb

    return [write_glb(out / f"{name}.glb", layers, aoi)]


def _obj(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.mesh import write_obj

    obj = write_obj(out / f"{name}.obj", layers, aoi)
    mtl = obj.with_suffix(".mtl")
    return [obj, mtl] if mtl.exists() else [obj]


def _epw(out: Path, name: str, aoi: AOI, layers: dict, metrics: dict) -> list[Path]:
    from .export.epw import write_epw

    return [write_epw(out / f"{name}.epw", layers, aoi)]


# fmt -> writer(out_dir, name, aoi, layers, metrics) -> written paths.
# Imports are lazy so optional extras (rhino3dm, trimesh) are only needed
# when that format is actually asked for.
EXPORTERS: dict[str, Callable[[Path, str, AOI, dict, dict], list[Path]]] = {
    "gpkg": _gpkg,
    "dxf": _dxf,
    "3dm": _3dm,
    "png": _png,
    "geojson": _geojson,
    "svg": _svg,
    "glb": _glb,
    "obj": _obj,
    "epw": _epw,
}


def run_exports(
    exports: Iterable[str], out: Path, name: str, aoi: AOI, layers: dict, metrics: dict
) -> list[Path]:
    """Write each requested format; returns every file written, in order."""
    written: list[Path] = []
    for fmt in exports:
        if fmt == "json":  # the dossier is always written by run_report
            continue
        written.extend(EXPORTERS[fmt](out, name, aoi, layers, metrics))
    return written


def analyse(layers: dict[str, LayerResult], aoi: AOI) -> tuple[dict[str, Any], dict[str, Any]]:
    """(metrics, coverage assessment) for already-fetched layers."""
    from .coverage import assess
    from .metrics import compute_all

    return compute_all(layers, aoi), assess(layers, aoi)


def run_report(
    aoi: AOI,
    layers: dict[str, LayerResult],
    out: Path,
    exports: Iterable[str] = (),
    *,
    sheet: bool = True,
    georef: bool = False,
) -> list[Path]:
    """Analyse fetched layers and write the dossier, optional PDF sheet and exports."""
    from .export.dossier import write_dossier

    out.mkdir(parents=True, exist_ok=True)
    name = aoi.name
    metrics, assessment = analyse(layers, aoi)
    written = [write_dossier(out / f"{name}.dossier.json", aoi, layers, metrics, assessment)]
    if sheet:
        from .report.sheet import render_sheet

        written.append(render_sheet(out / f"{name}.pdf", aoi, layers, metrics, assessment))
    written.extend(run_exports(exports, out, name, aoi, layers, metrics))
    if georef:
        from .export._georef import write_georef

        written.append(write_georef(out / "georef.json", aoi))
    return written
