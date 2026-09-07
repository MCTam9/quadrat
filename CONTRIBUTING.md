# Contributing: the contract every provider and metric is written against

Read this before adding a provider, a metric or an export. It is the shape the
whole codebase assumes, and most of it exists because getting it wrong is
expensive to undo later.

```bash
pip install -e ".[dev]"
pytest
```

Site Context Report (`sce`): coordinates and a radius anywhere on earth to an A3
sheet plus machine-readable data covering urban morphology, terrain, climate and
access.

## The spine

These four modules define the contract. Changing them changes everything
downstream, so change them deliberately and expect the meta-tests to argue.

- `sce/aoi.py` — the CRS spine. `AOI.from_point(lon, lat, radius_m, name)`.
  Key API: `aoi.crs` (pyproj CRS, always projected metres), `aoi.geometry`
  (shapely Polygon, a square, in `aoi.crs`), `aoi.centroid_lonlat` -> (lon, lat),
  `aoi.bbox_wgs84` -> (w, s, e, n), `aoi.geometry_wgs84`, `aoi.area_m2`,
  `aoi.area_ha`, `aoi.area_km2`, `aoi.epsg` (e.g. "EPSG:32642"),
  `aoi.to_metric(gdf)`, `aoi.clip(gdf)`, `aoi.key()`, `aoi.provenance()`.
  Also `assert_metric_crs(crs, where=...)` which raises `NonMetricCRSError`
  on any geographic CRS. `WGS84` is exported from this module.
- `sce/types.py` — `Source`, `LayerResult`, `Provider`.
- `sce/cache.py` — `Cache(root=None, offline=None)`, with `.key(*parts)`,
  `.get_bytes(key, suffix, producer)`, `.get_json(key, producer)`.
  `producer` is a zero-arg callable returning `(payload, meta_dict)`.
  When `cache.offline` is True and there is no hit, it raises `FileNotFoundError`.
- `sce/registry.py` — `REGISTRY.register(provider)`, `REGISTRY.fetch(layer, aoi, cache, override=None, allow_non_commercial=False)`.

## Provider contract

Subclass `sce.types.Provider`. Declare class attributes `name`, `layer`,
`licence`, `rank` (lower runs first), and `commercial_ok` (False only for
non-commercial licences such as FABDEM; the registry then skips it unless the
user opts in). Implement:

- `available(self, aoi) -> bool` — cheap, no network. e.g. UK-only providers
  return True only when `aoi.centroid_lonlat` falls in GB.
- `fetch(self, aoi, cache) -> LayerResult` — returns geometry **already in
  `aoi.crs`**. Never return WGS84. Attach at least one `Source(name, url,
  licence, licence_url=..., commercial_ok=...)`. Set `coverage` (0..1) and
  `degraded=True` where the provider can judge its own completeness.

Register at import time at the bottom of the module: `REGISTRY.register(MyProvider())`.

`LayerResult` fields: `layer, provider, gdf, raster, data, sources, coverage,
degraded, notes`. For rasters set `raster = {"array": np.ndarray, "transform":
affine.Affine, "crs": <metric CRS>, "nodata": value, "res": (dx, dy)}` with the
array **already reprojected to the AOI metric CRS on a square grid**.

## Layer names (fixed vocabulary)

`streets`, `buildings`, `landuse`, `landcover`, `amenities`, `terrain`,
`climate`, `constraints`, `building_height`.

`building_height` is not a footprint layer: it carries no per-building
geometry, only a reprojected raster plus `data={"mean_height_m": ...}`. It
exists as a floor-space-index FALLBACK for when the `buildings` layer's own
OSM height coverage is too sparse to trust (see `sce/providers/height_ghsl.py`
and `sce/metrics/fabric.py`).

## Metric contract

Every metric function lives in `sce/metrics/*.py`, takes the layer results it
needs plus the `aoi`, and **calls `assert_metric_crs(...)` on the first line
that touches geometry**. There is a meta-test that hands every registered metric
geographic input and asserts it raises. Register metrics in
`sce/metrics/__init__.py` in a dict `METRICS: dict[str, Callable]`.

Metrics return a flat `dict[str, float | int | str | None]` plus, where a value
is uncertain, a companion `"<key>_source"` or `"<key>_coverage"` entry. Never
invent a number: when coverage is too low, return None and report the coverage.

## Traps that must be handled (these are graded)

1. Buffer the projected centre, never degrees. `AOI` already does this — use it.
2. `make_valid` then `union_all()` before ANY footprint area sum, or ground
   space index exceeds 1.0 in dense blocks.
3. Reproject the DEM window to a square metre grid **before** computing slope.
4. Copernicus GLO-30 is a DSM (includes rooftops and trees), not a DTM. Say so.
5. Use `aoi.area_m2` as the single area denominator for every density.
6. Normalise osmnx orientation entropy from nats to 0..1 before printing.

## Style

Type hints, `from __future__ import annotations`, no comments that restate the
code, docstrings that explain *why*. Line length 100. No new dependencies
without saying so. Prefer stdlib and what is already installed:
osmnx 2.1.1, geopandas 1.1.4, shapely 2.x, pyproj, rasterio 1.5.1, matplotlib,
numpy, pandas, requests, networkx, pyarrow, ezdxf 1.4.4, click.

## Tests

Tests go in `tests/unit/`. Tests that hit the network go in `tests/live/`,
marked `@pytest.mark.live`, and are excluded from a plain `pytest` run. Zero network in unit tests. Use synthetic geometry
with analytically known answers wherever possible (e.g. a perfect 1 km grid has
orientation order phi = 1.0). Do not snapshot floats you have not reasoned about.
