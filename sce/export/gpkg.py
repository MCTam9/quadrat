"""Layered GeoPackage export. Every layer lands in the AOI metric CRS.

GPKG reserves the column names `fid` and `geom` (and forbids empty-all-null
columns surviving a round trip cleanly on some drivers), so attribute frames
are sanitised before `to_file`. Metrics/provenance go into a non-spatial
attribute table in the same file when pyogrio allows a non-spatial layer,
else a sidecar JSON next to the .gpkg.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from ..types import LayerResult

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


def _aoi_gdf(aoi) -> gpd.GeoDataFrame:  # noqa: ANN001
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
    aoi,  # noqa: ANN001
    metrics: dict[str, dict] | None = None,
) -> Path:
    """Write every layer's geometry plus the AOI square to a layered GPKG.

    Metrics/provenance are attempted as a non-spatial attribute table in the
    same GPKG (pyogrio permits this via a plain DataFrame `to_file`); if that
    fails for any reason we fall back to a sidecar `<path>.attributes.json`
    so the information is never silently lost.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    _aoi_gdf(aoi).to_file(path, layer="aoi", driver="GPKG")

    written: list[str] = ["aoi"]
    for name, result in sorted(layers.items()):
        if result is None or result.gdf is None or len(result.gdf) == 0:
            continue
        gdf = result.gdf
        if gdf.crs is None or gdf.crs != aoi.crs:
            gdf = aoi.to_metric(gdf)
        gdf = _sanitize_gdf(gdf)
        if gdf.geometry.name != "geometry":
            gdf = gdf.set_geometry(gdf.geometry.name)
        gdf.to_file(path, layer=name, driver="GPKG")
        written.append(name)

    attrs_written = False
    if metrics or layers:
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
        if rows:
            df = pd.DataFrame(rows)
            df = df.rename(columns={c: _sanitize_column_name(c) for c in df.columns})
            try:
                pyogrio.write_dataframe(df, path, layer="attributes", driver="GPKG")
                attrs_written = True
            except Exception:
                attrs_written = False

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
