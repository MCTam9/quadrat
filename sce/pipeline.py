"""The report pipeline as plain functions, shared by the CLI and the web API.

`cli.py` used to own this sequence privately. The web backend needs the same
steps without click, so they live here and the CLI is now a thin shell that
prints progress.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .aoi import AOI
from .types import LayerResult

log = logging.getLogger("sce.pipeline")

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


DraftCallback = Callable[[str, LayerResult], None]

DEFAULT_OVERPASS_BUDGET_S = 90.0


def overpass_budget_s() -> float:
    """Seconds the Overpass-backed layers get before map tiles stand in (env `SCE_OVERPASS_BUDGET_S`)."""
    try:
        v = float(os.environ.get("SCE_OVERPASS_BUDGET_S", DEFAULT_OVERPASS_BUDGET_S))
    except ValueError:
        return DEFAULT_OVERPASS_BUDGET_S
    return v if v > 0 else DEFAULT_OVERPASS_BUDGET_S


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
    on_draft: DraftCallback | None = None,
    overpass_budget_s: float | None = None,
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

    Map-tile drafts (parallel runs only). When `on_draft` or `overpass_budget_s` is
    given, the OpenFreeMap tiles for the AOI are fetched once, at the very start, in
    their own thread (`sce.providers.openfreemap_tiles.tile_results`). As soon as they
    decode, `on_draft(name, result)` fires for each of buildings, streets, landuse and
    amenities that has not completed yet; a draft is never delivered after its layer's
    real result, and a real result never replaces one that was already delivered.
    `overpass_budget_s` is the deadline for the Overpass-backed layers: layers still
    pending when it passes finish from the same tile results (through the registry, as
    the `tiles_*` provider, with a note), and the late Overpass answer is discarded. If
    the tiles themselves are unavailable the Overpass layers are simply waited for.
    """
    import sce.providers  # noqa: F401  - registers providers

    from .registry import REGISTRY

    override = override or {}
    wanted = [layer for layer in (list(only) if only else list(LAYERS)) if REGISTRY.chain(layer, aoi)]
    results: dict[str, LayerResult | None] = {}
    t0 = time.perf_counter()
    lock = threading.Lock()
    # Layers whose final result has been delivered. Checked under `lock` by both a
    # draft (so it never lands after the real layer) and a late worker (so an
    # abandoned Overpass answer never replaces the tile fallback).
    completed: set[str] = set()
    abandoned: set[str] = set()

    def finish(layer: str, result: LayerResult | None, started: float) -> None:
        with lock:
            if layer in completed:
                return
            completed.add(layer)
            results[layer] = result
            if timings is not None:
                timings[layer] = round((time.perf_counter() - started) * 1000)
        if on_layer is not None:
            on_layer(layer, result)

    def one(layer: str) -> None:
        started = time.perf_counter()
        result = REGISTRY.fetch(
            layer,
            height_focus if layer == "building_height" and height_focus is not None else aoi,
            cache,
            override=override.get(layer),
            allow_non_commercial=allow_nc,
        )
        finish(layer, result, started)

    if not parallel:
        for layer in wanted:
            one(layer)
    else:
        osm = {layer for group in OSM_GROUPS for layer in group}
        groups = [[layer for layer in group if layer in wanted] for group in OSM_GROUPS]
        groups = [g for g in groups if g]
        independent = [layer for layer in wanted if layer not in osm]
        errors: list[Exception] = []

        def run_group(group: list[str]) -> None:
            for layer in group:
                if layer in abandoned:
                    continue
                try:
                    one(layer)
                except Exception as exc:
                    errors.append(exc)

        def draft_worker() -> None:
            from .providers.openfreemap_tiles import TILE_LAYERS, tile_results

            try:
                tiles = tile_results(aoi, cache)
            except Exception as exc:
                log.info("map-tile drafts unavailable: %s", exc)
                return
            for layer in TILE_LAYERS:
                if layer not in wanted or override.get(layer) or layer not in tiles:
                    continue
                with lock:
                    if layer in completed:
                        continue
                    try:
                        if on_draft is not None:
                            on_draft(layer, tiles[layer])
                    except Exception:
                        log.warning("draft callback failed for %s", layer, exc_info=True)

        def spawn(fn: Callable[..., None], *args: Any, name: str) -> threading.Thread:
            # Daemon threads: an abandoned Overpass request must not hold the process open.
            t = threading.Thread(target=fn, args=args, name=name, daemon=True)
            t.start()
            return t

        use_tiles = on_draft is not None or overpass_budget_s is not None
        if use_tiles and not override.keys() & {"buildings", "streets", "landuse", "amenities"}:
            spawn(draft_worker, name="sce-tile-drafts")
        osm_threads = [(g, spawn(run_group, g, name=f"sce-{g[0]}")) for g in groups]
        others = [spawn(one, layer, name=f"sce-{layer}") for layer in independent]

        deadline = None if overpass_budget_s is None else t0 + overpass_budget_s
        for group, thread in osm_threads:
            thread.join(None if deadline is None else max(0.0, deadline - time.perf_counter()))
            if not thread.is_alive():
                continue
            # Over budget: finish what is pending from the tiles, then stop waiting for this group.
            unresolved = False
            for layer in group:
                with lock:
                    if layer in completed:
                        continue
                fallback = _tiles_fallback(layer, aoi, cache, REGISTRY, overpass_budget_s)
                if fallback is None:
                    unresolved = True
                    continue
                with lock:
                    abandoned.add(layer)
                finish(layer, fallback, t0)
            if unresolved:
                thread.join()  # some layer has no tiles to stand in: Overpass is all there is
        for t in others:
            t.join()
        if errors:
            raise errors[0]

    layers = {layer: results[layer] for layer in wanted if results.get(layer) is not None}
    # Where a per-building-resolution height raster exists (EA LiDAR in England),
    # measure the buildings OSM left without a height. A no-op elsewhere.
    from .heights import enrich_building_heights

    started = time.perf_counter()
    enriched = enrich_building_heights(layers)
    if timings is not None:
        timings["heights"] = round((time.perf_counter() - started) * 1000)
    return enriched


def _tiles_fallback(layer: str, aoi: AOI, cache: Any, registry: Any, budget_s: float) -> LayerResult | None:
    """The map-tile result for `layer` through the registry (the `tiles_*` provider), or None."""
    from .providers.openfreemap_tiles import TILE_LAYERS

    if layer not in TILE_LAYERS:
        return None
    result = registry.fetch(layer, aoi, cache, override=f"tiles_{layer}")
    if result is not None:
        result.notes.append(f"Overpass did not answer within {budget_s:g} s; map tiles stand in")
    return result


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
    title: str | None = None,
) -> list[Path]:
    """Analyse fetched layers and write the dossier, optional PDF sheet and exports.

    `title` heads the sheet (the place name the web app shows); file names keep `aoi.name`.
    """
    from .export.dossier import write_dossier

    out.mkdir(parents=True, exist_ok=True)
    name = aoi.name
    metrics, assessment = analyse(layers, aoi)
    written = [write_dossier(out / f"{name}.dossier.json", aoi, layers, metrics, assessment)]
    if sheet:
        from .report.sheet import render_sheet

        written.append(render_sheet(out / f"{name}.pdf", aoi, layers, metrics, assessment, title=title))
    written.extend(run_exports(exports, out, name, aoi, layers, metrics))
    if georef:
        from .export._georef import write_georef

        written.append(write_georef(out / "georef.json", aoi))
    return written
