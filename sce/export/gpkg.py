"""Layered GeoPackage export. Every layer lands in the AOI metric CRS.

GPKG reserves the column names `fid` and `geom` (and forbids empty-all-null
columns surviving a round trip cleanly on some drivers), so attribute frames
are sanitised before they go through `gpkg_writer` (stdlib sqlite3, so the API
bundle needs no GDAL/pyogrio). Metrics/provenance go into a non-spatial
attribute table in the same file, else a sidecar JSON next to the .gpkg.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from ..types import LayerResult
from .gpkg_writer import write_layers

_RESERVED = {"fid", "geom", "geometry"}


def _sanitize_column_name(name: str) -> str:
    if name.lower() in _RESERVED and name != "geometry":
        return f"{name}_attr"
    return name


def _sanitize_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    rename = {}
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        new = _sanitize_column_name(col)
        if new != col:
            rename[col] = new
    if rename:
        gdf = gdf.rename(columns=rename)

    drop = []
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        series = gdf[col]
        if series.isna().all():
            drop.append(col)
            continue
        if series.apply(lambda v: isinstance(v, (list, dict))).any():
            gdf[col] = series.apply(lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v)
    if drop:
        gdf = gdf.drop(columns=drop)
    return gdf


def _aoi_gdf(aoi) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": [aoi.name], "epsg": [aoi.epsg], "area_ha": [round(aoi.area_ha, 4)]},
        geometry=[aoi.geometry],
        crs=aoi.crs,
    )


def _flatten_for_table(prefix: str, obj: Any, out: dict[str, Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_for_table(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(obj, (list, tuple)):
        out[prefix] = json.dumps(obj)
    else:
        out[prefix] = obj


def write_gpkg(
    path: str | Path,
    layers: dict[str, LayerResult],
    aoi,
    metrics: dict[str, dict] | None = None,
) -> Path:
    """Write every layer's geometry plus the AOI square to a layered GPKG.

    Metrics/provenance are attempted as a non-spatial attribute table in the
    same GPKG; if that fails for any reason we fall back to a sidecar `<path>.attributes.json`
    so the information is never silently lost.
    """
    path = Path(path)

    frames: dict[str, pd.DataFrame] = {"aoi": _aoi_gdf(aoi)}
    for name, result in sorted(layers.items()):
        if result is None or result.gdf is None or len(result.gdf) == 0:
            continue
        gdf = result.gdf
        if gdf.crs is None or gdf.crs != aoi.crs:
            gdf = aoi.to_metric(gdf)
        frames[name] = _sanitize_gdf(gdf)

    attrs = _attributes_frame(layers, metrics)
    attrs_written = False
    try:
        write_layers(path, {**frames, "attributes": attrs} if attrs is not None else frames)
        attrs_written = attrs is not None
    except Exception:
        if attrs is None:
            raise
        write_layers(path, frames)

    if not attrs_written and metrics:
        sidecar = path.with_suffix(path.suffix + ".attributes.json")
        sidecar.write_text(
            json.dumps(
                {
                    "layer_provenance": {k: v.provenance() for k, v in sorted(layers.items()) if v},
                    "metrics": metrics,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    return path


def _attributes_frame(layers: dict[str, LayerResult], metrics: dict[str, dict] | None) -> pd.DataFrame | None:
    if not (metrics or layers):
        return None
    rows: list[dict[str, Any]] = []
    for layer_name, result in sorted(layers.items()):
        if result is None:
            continue
        flat: dict[str, Any] = {"kind": "layer_provenance", "layer": layer_name}
        _flatten_for_table("", result.provenance(), flat)
        rows.append(flat)
    for metric_name, values in sorted((metrics or {}).items()):
        flat = {"kind": "metric", "layer": metric_name}
        _flatten_for_table("", values, flat)
        rows.append(flat)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return df.rename(columns={c: _sanitize_column_name(c) for c in df.columns})
