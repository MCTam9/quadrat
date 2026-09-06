"""Command line entry point.

One command per verb, and the same command for every site on earth. Where
richer data exists the sheet gets richer; nothing about the invocation changes.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from . import __version__
from .aoi import AOI

LAYERS = ("streets", "buildings", "landuse", "landcover", "amenities", "terrain", "climate", "constraints")

# Above this the Overpass download is huge and the figure-ground degrades into a
# grey smudge, so it is deliberately behind a flag.
RADIUS_WARN_M = 5000


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _build_aoi(coords: str | None, geojson: str | None, radius: float, name: str) -> AOI:
    if geojson:
        obj = json.loads(Path(geojson).read_text())
        return AOI.from_geojson(obj, name=name)
    if not coords:
        raise click.UsageError("give --coords 'lon,lat' or --geojson path")
    try:
        lon_s, lat_s = coords.split(",")
        lon, lat = float(lon_s), float(lat_s)
    except ValueError as exc:
        raise click.UsageError("--coords must be 'lon,lat' in decimal degrees") from exc
    return AOI.from_point(lon, lat, radius, name=name)


def _fetch_layers(aoi: AOI, cache, only, override, allow_nc: bool) -> dict:
    from .registry import REGISTRY

    wanted = only or LAYERS
    layers: dict = {}
    for layer in wanted:
        if not REGISTRY.chain(layer, aoi):
            continue
        click.echo(f"  {layer:<12} ", nl=False, err=True)
        result = REGISTRY.fetch(
            layer, aoi, cache, override=override.get(layer), allow_non_commercial=allow_nc
        )
        if result is None:
            click.echo("none", err=True)
            continue
        layers[layer] = result
        n = len(result.gdf) if result.gdf is not None else ("raster" if result.raster is not None else "data")
        cov = "" if result.coverage is None else f", coverage {result.coverage:.0%}"
        click.echo(f"{result.provider} ({n}{cov})", err=True)
    return layers


@click.group()
@click.version_option(__version__, prog_name="sce")
def main() -> None:
    """Site Context Report - urban morphology, terrain, climate and access, anywhere."""


@main.command()
@click.option("--coords", help="lon,lat in decimal degrees")
@click.option("--geojson", type=click.Path(exists=True), help="WGS84 boundary instead of a point")
@click.option("--radius", default=1500.0, show_default=True, help="metres; the AOI is a square of this half-width")
@click.option("--name", default="site", show_default=True)
@click.option("--out", "outdir", default="out", show_default=True, type=click.Path())
@click.option("--layer", "only", multiple=True, type=click.Choice(LAYERS), help="restrict to these layers")
@click.option("--provider", "overrides", multiple=True, help="layer=provider_name to force one provider")
@click.option("--dtm", type=click.Choice(["dsm", "fabdem"]), default="dsm", show_default=True,
              help="fabdem is bare-earth but CC BY-NC-SA, so non-commercial only")
@click.option("--export", "exports", multiple=True, type=click.Choice(["gpkg", "dxf", "json", "png", "3dm"]),
              help="repeatable; the PDF sheet is always written")
@click.option("--force", is_flag=True, help="permit a radius above 5 km")
@click.option("--no-sheet", is_flag=True, help="skip the PDF, useful when you only want data")
@click.option("-v", "--verbose", is_flag=True)
def report(coords, geojson, radius, name, outdir, only, overrides, dtm, exports, force, no_sheet, verbose) -> None:
    """Build the site context report for one site."""
    _setup_logging(verbose)
    if radius > RADIUS_WARN_M and not force:
        raise click.UsageError(
            f"--radius {radius:.0f} m is above {RADIUS_WARN_M} m. The download is large and the "
            "figure-ground stops reading as a drawing. Pass --force if you mean it."
        )

    import sce.providers  # noqa: F401  - registers providers

    from .cache import Cache
    from .coverage import assess
    from .export.dossier import write_dossier
    from .metrics import compute_all

    aoi = _build_aoi(coords, geojson, radius, name)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    click.echo(f"{aoi.name}: {aoi.centroid_lonlat[0]:.5f},{aoi.centroid_lonlat[1]:.5f} "
               f"r={radius:.0f} m  {aoi.epsg}  {aoi.area_ha:.0f} ha", err=True)

    override = dict(o.split("=", 1) for o in overrides)
    if dtm == "fabdem":
        override["terrain"] = "fabdem"
        click.secho("  FABDEM is CC BY-NC-SA 4.0: non-commercial use only. "
                    "The licence is printed on the sheet.", fg="yellow", err=True)

    cache = Cache()
    layers = _fetch_layers(aoi, cache, list(only), override, allow_nc=(dtm == "fabdem"))
    if not layers:
        raise click.ClickException("no layer returned data; check connectivity")

    metrics = compute_all(layers, aoi)
    warnings = assess(layers, aoi)

    dossier = write_dossier(out / f"{name}.dossier.json", aoi, layers, metrics, warnings)
    click.echo(f"  wrote {dossier}", err=True)

    if not no_sheet:
        from .report.sheet import render_sheet

        pdf = render_sheet(out / f"{name}.pdf", aoi, layers, metrics, warnings)
        click.echo(f"  wrote {pdf}", err=True)

    _run_exports(exports, out, name, aoi, layers, metrics)
    click.secho(f"done: {out}", fg="green", err=True)


def _run_exports(exports, out: Path, name: str, aoi, layers, metrics) -> None:
    for fmt in exports:
        if fmt == "gpkg":
            from .export.gpkg import write_gpkg
            from .export.qml import write_qml_styles

            p = write_gpkg(out / f"{name}.gpkg", layers, aoi, metrics)
            write_qml_styles(p, layers)
            click.echo(f"  wrote {p} (+ QGIS styles)", err=True)
        elif fmt == "dxf":
            from .export.dxf import write_dxf

            click.echo(f"  wrote {write_dxf(out / f'{name}.dxf', layers, aoi)}", err=True)
        elif fmt == "3dm":
            from .export.rhino import write_3dm

            click.echo(f"  wrote {write_3dm(out / f'{name}.3dm', layers, aoi)}", err=True)
        elif fmt == "png":
            from .report.sheet import render_sheet

            click.echo(f"  wrote {render_sheet(out / f'{name}.png', aoi, layers, metrics, None)}", err=True)


@main.command()
@click.argument("sites", nargs=-1, required=True)
@click.option("--radius", default=1500.0, show_default=True)
@click.option("--out", "outdir", default="out", show_default=True, type=click.Path())
@click.option("-v", "--verbose", is_flag=True)
def compare(sites, radius, outdir, verbose) -> None:
    """Benchmark sites side by side. SITES are name=lon,lat pairs.

    The table is normalised but carries NO composite score. Weights belong to
    the client, not the tool.
    """
    _setup_logging(verbose)
    import sce.providers  # noqa: F401

    from .cache import Cache
    from .metrics import compute_all
    from .report.compare import render_compare

    cache = Cache()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    bundle = []
    for spec in sites:
        name, _, coords = spec.partition("=")
        aoi = _build_aoi(coords or name, None, radius, name or "site")
        click.echo(f"{aoi.name}: {aoi.epsg}", err=True)
        layers = _fetch_layers(aoi, cache, [], {}, allow_nc=False)
        bundle.append((aoi, layers, compute_all(layers, aoi)))

    pdf = render_compare(out / "compare.pdf", bundle)
    click.secho(f"wrote {pdf}", fg="green", err=True)


@main.command()
def providers() -> None:
    """List every registered provider, its layer, rank and licence."""
    import sce.providers  # noqa: F401

    from .registry import REGISTRY

    for layer in REGISTRY.layers():
        click.secho(layer, bold=True)
        for p in REGISTRY.providers(layer):
            flag = "" if p.commercial_ok else "  [non-commercial]"
            click.echo(f"  {p.rank:>3}  {p.name:<24} {p.licence}{flag}")


@main.command()
@click.option("--out", default="ATTRIBUTION.md", type=click.Path())
def attribution(out) -> None:
    """Regenerate ATTRIBUTION.md from the provider registry."""
    import sce.providers  # noqa: F401

    from .export.attribution import generate_attribution
    from .registry import REGISTRY

    click.echo(f"wrote {generate_attribution(REGISTRY, Path(out))}")


if __name__ == "__main__":
    main()
