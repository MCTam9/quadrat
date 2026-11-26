"""A minimal GeoPackage 1.4 writer on the standard library's `sqlite3`.

Why it exists: the only thing that needed pyogrio was writing GeoPackages, and pyogrio ships
its own copy of GDAL (~100 MB) next to rasterio's. A GeoPackage is just SQLite with a few
metadata tables and a small header in front of each WKB geometry, so we write it directly.
Dev installs still have pyogrio, and the tests read every file back through GDAL.

Covers what the export needs: feature tables (one geometry column named `geom`), attribute-only
tables, one SRS per layer, and an R-tree spatial index (skipped if the sqlite build lacks rtree).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
from geopandas import GeoDataFrame
from pyproj import CRS

APPLICATION_ID = 0x47504B47  # "GPKG"
USER_VERSION = 10400  # GeoPackage 1.4.0
GEOM_COLUMN = "geom"
_LE_XY = 0b0000_0011  # little-endian, envelope = XY
_LE_EMPTY = 0b0001_0001  # little-endian, no envelope, empty geometry

_SCHEMA = """
CREATE TABLE gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
  organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
CREATE TABLE gpkg_contents (
  table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
  description TEXT DEFAULT '',
  last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
  CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
CREATE TABLE gpkg_geometry_columns (
  table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
  CONSTRAINT uk_gc_table_name UNIQUE (table_name),
  CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
  CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
CREATE TABLE gpkg_extensions (
  table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL, definition TEXT NOT NULL,
  scope TEXT NOT NULL, CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name));
"""

_TYPE_NAMES = {
    0: "POINT",
    1: "LINESTRING",
    3: "POLYGON",
    4: "MULTIPOINT",
    5: "MULTILINESTRING",
    6: "MULTIPOLYGON",
}
_RTREE_URL = "http://www.geopackage.org/spec120/#extension_rtree"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _is_null(v: Any) -> bool:
    return v is None or v is pd.NA or v is pd.NaT or (isinstance(v, float) and v != v)


def _sql_type(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DATETIME"
    return "TEXT"


def _cell(v: Any) -> Any:
    if _is_null(v):
        return None
    if isinstance(v, (str, int, float, bytes)):  # bool is an int
        return v
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        return v.isoformat()
    return str(v)


def _geom_type_name(geoms: np.ndarray) -> str:
    kinds = {int(shapely.get_type_id(g)) for g in geoms if g is not None}
    if len(kinds) == 1 and (k := next(iter(kinds))) in _TYPE_NAMES:
        return _TYPE_NAMES[k]
    return "GEOMETRY"


def _blobs(geoms: np.ndarray, srs_id: int) -> list[bytes | None]:
    """GeoPackage binary: "GP", version 0, flags, int32 srs_id, XY envelope, then WKB."""
    wkbs = shapely.to_wkb(geoms, output_dimension=2, byte_order=1)
    bounds = shapely.bounds(geoms)
    empty = shapely.is_empty(geoms)
    out: list[bytes | None] = []
    for wkb_, (x0, y0, x1, y1), is_empty, g in zip(wkbs, bounds, empty, geoms, strict=True):
        if g is None:
            out.append(None)
        elif is_empty:
            out.append(b"GP\x00" + bytes([_LE_EMPTY]) + struct.pack("<i", srs_id) + wkb_)
        else:
            out.append(b"GP\x00" + bytes([_LE_XY]) + struct.pack("<i4d", srs_id, x0, x1, y0, y1) + wkb_)
    return out


def _rows(df: pd.DataFrame, cols: list[str], blobs: list[bytes | None] | None) -> Iterator[tuple]:
    columns = [df[c].tolist() for c in cols]
    for i in range(len(df)):
        row: list[Any] = [i + 1]
        if blobs is not None:
            row.append(blobs[i])
        row.extend(_cell(col[i]) for col in columns)
        yield tuple(row)


def _add_rtree(con: sqlite3.Connection, table: str, geoms: np.ndarray) -> None:
    rt = f"rtree_{table}_{GEOM_COLUMN}"
    t, c, r = _q(table), _q(GEOM_COLUMN), _q(rt)
    try:
        con.execute(f"CREATE VIRTUAL TABLE {r} USING rtree(id, minx, maxx, miny, maxy)")
    except sqlite3.OperationalError:
        return
    bounds = shapely.bounds(geoms)
    keep = ~shapely.is_empty(geoms) & ~np.isnan(bounds).any(axis=1)
    con.executemany(
        f"INSERT INTO {r} VALUES (?,?,?,?,?)",
        (
            (int(i) + 1, b[0], b[2], b[1], b[3])
            for i, b in zip(np.flatnonzero(keep), bounds[keep], strict=True)
        ),
    )
    con.execute(
        "INSERT INTO gpkg_extensions VALUES (?,?,?,?,?)",
        (table, GEOM_COLUMN, "gpkg_rtree_index", _RTREE_URL, "write-only"),
    )
    env = f"ST_MinX(NEW.{c}), ST_MaxX(NEW.{c}), ST_MinY(NEW.{c}), ST_MaxY(NEW.{c})"
    ins = f"INSERT OR REPLACE INTO {r} VALUES (NEW.fid, {env})"
    drop_old = f"DELETE FROM {r} WHERE id = OLD.fid"
    ok = f"(NEW.{c} NOT NULL AND NOT ST_IsEmpty(NEW.{c}))"
    gone = f"(NEW.{c} ISNULL OR ST_IsEmpty(NEW.{c}))"
    # Standard GeoPackage 1.4 triggers. They call ST_* functions that GDAL registers when it
    # opens the file; sqlite3 here never fires them, so they are created after the bulk fill.
    triggers = {
        "insert": f"AFTER INSERT ON {t} WHEN {ok} BEGIN {ins}; END",
        "update1": f"AFTER UPDATE OF {c} ON {t} WHEN OLD.fid = NEW.fid AND {ok} BEGIN {ins}; END",
        "update2": f"AFTER UPDATE OF {c} ON {t} WHEN OLD.fid = NEW.fid AND {gone} BEGIN {drop_old}; END",
        "update3": f"AFTER UPDATE ON {t} WHEN OLD.fid != NEW.fid AND {ok} BEGIN {drop_old}; {ins}; END",
        "update4": (
            f"AFTER UPDATE ON {t} WHEN OLD.fid != NEW.fid AND {gone} "
            f"BEGIN DELETE FROM {r} WHERE id IN (OLD.fid, NEW.fid); END"
        ),
        "delete": f"AFTER DELETE ON {t} WHEN OLD.{c} NOT NULL BEGIN {drop_old}; END",
    }
    for suffix, body in triggers.items():
        con.execute(f"CREATE TRIGGER {_q(f'{rt}_{suffix}')} {body}")


def _srs_id(df: pd.DataFrame, srs_ids: dict[str, int]) -> int:
    return srs_ids.get(df.crs.to_wkt(), 0) if df.crs is not None else 0


def _write_table(con: sqlite3.Connection, name: str, df: pd.DataFrame, srs_ids: dict[str, int]) -> None:
    is_geo = isinstance(df, GeoDataFrame) and df._geometry_column_name is not None
    cols = [c for c in df.columns if not (is_geo and c == df.geometry.name)]
    for c in cols:
        if str(c).lower() in {"fid", GEOM_COLUMN}:
            raise ValueError(f"column {c!r} in layer {name!r} collides with a reserved GeoPackage name")
    defs = ["fid INTEGER PRIMARY KEY AUTOINCREMENT"]
    if is_geo:
        defs.append(f"{_q(GEOM_COLUMN)} BLOB")
    defs += [f"{_q(str(c))} {_sql_type(df[c])}" for c in cols]
    con.execute(f"CREATE TABLE {_q(name)} ({', '.join(defs)})")

    geoms = blobs = None
    srs_id = 0
    if is_geo:
        geoms = np.asarray(df.geometry.values, dtype=object)
        srs_id = _srs_id(df, srs_ids)
        blobs = _blobs(geoms, srs_id)
    names = ["fid"] + ([_q(GEOM_COLUMN)] if is_geo else []) + [_q(str(c)) for c in cols]
    marks = ",".join("?" * len(names))
    con.executemany(f"INSERT INTO {_q(name)} ({','.join(names)}) VALUES ({marks})", _rows(df, cols, blobs))

    if geoms is None:
        con.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier) VALUES (?,?,?)",
            (name, "attributes", name),
        )
        return
    bounds = shapely.bounds(geoms)
    bounds = bounds[~np.isnan(bounds).any(axis=1)]
    ext: tuple[float | None, ...] = (None, None, None, None)
    if len(bounds):
        ext = (
            float(bounds[:, 0].min()),
            float(bounds[:, 1].min()),
            float(bounds[:, 2].max()),
            float(bounds[:, 3].max()),
        )
    con.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, min_x, min_y, max_x, max_y, srs_id)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (name, "features", name, *ext, srs_id),
    )
    con.execute(
        "INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
        (name, GEOM_COLUMN, _geom_type_name(geoms), srs_id, 0, 0),
    )
    _add_rtree(con, name, geoms)


def _spatial_refs(layers: dict[str, pd.DataFrame]) -> tuple[dict[int, tuple], dict[str, int]]:
    rows: dict[int, tuple] = {
        -1: ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined Cartesian CRS"),
        0: ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic CRS"),
        4326: ("WGS 84", 4326, "EPSG", 4326, CRS.from_epsg(4326).to_wkt(), "WGS 84 longitude/latitude"),
    }
    ids: dict[str, int] = {}
    for df in layers.values():
        if not isinstance(df, GeoDataFrame) or df.crs is None:
            continue
        wkt = df.crs.to_wkt()
        if wkt in ids:
            continue
        code = df.crs.to_epsg()
        if code is not None:
            ids[wkt] = code
            rows.setdefault(code, (df.crs.name, code, "EPSG", code, wkt, None))
        else:  # no EPSG code: ids above the range the spec reserves
            code = 100000 + len(ids)
            ids[wkt] = code
            rows[code] = (df.crs.name or "custom", code, "NONE", code, wkt, None)
    return rows, ids


def write_layers(path: str | Path, layers: dict[str, pd.DataFrame]) -> Path:
    """Write each frame as a table in one new GeoPackage at `path` (replacing any file there).

    A GeoDataFrame becomes a feature table with a `geom` column in its CRS; a plain DataFrame
    becomes an attribute-only table. NaN and None are stored as NULL.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    srs_rows, srs_ids = _spatial_refs(layers)

    con = sqlite3.connect(path)
    try:
        con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        con.execute(f"PRAGMA user_version = {USER_VERSION}")
        con.executescript(_SCHEMA)
        con.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", srs_rows.values())
        for name, df in layers.items():
            _write_table(con, name, df, srs_ids)
        con.commit()
    finally:
        con.close()
    return path
