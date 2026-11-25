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
  (shapely Polygon in `aoi.crs`: a square aligned to TRUE north, so in UTM it sits
  rotated by the grid convergence, up to ~3 deg; never assume an axis-aligned box,
  and blank raster cells outside it with `_terrain_grid.inside_aoi`), `aoi.centroid_lonlat` -> (lon, lat),
  `aoi.bbox_wgs84` -> (w, s, e, n), `aoi.geometry_wgs84`, `aoi.area_m2`,
  `aoi.area_ha`, `aoi.area_km2`, `aoi.epsg` (e.g. "EPSG:32642"),
  `aoi.to_metric(gdf)`, `aoi.clip(gdf)`, `aoi.key()`, `aoi.provenance()`.
  `from_point(..., crs=...)` pins the CRS instead of choosing one; the web app
  uses it so a square cut from a padded fetch shares that fetch's CRS.
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
  licence, licence_url=..., commercial_ok=...)`. End with
  `return self.summarise(result, aoi)`.
- `summarise(self, result, aoi) -> LayerResult` — pure, no I/O: given a result
  already confined to `aoi`, set `coverage` (0..1), `degraded`, `findings` and any
  square-dependent `data` (mean height, class fractions, elevation summary).
  It runs at fetch **and** whenever the web app clips a smaller square, so each
  rule lives once. Count raster cells with `_terrain_grid.inside_aoi`, never
  over the whole array.

Register at import time at the bottom of the module: `REGISTRY.register(MyProvider())`.

`LayerResult` fields: `layer, provider, gdf, raster, data, sources, coverage,
degraded, notes, findings`. `notes` are facts that hold for any square (licence
caveats, "fell back after"); `findings` depend on the square and are rewritten
by `summarise`. For rasters set `raster = {"array": np.ndarray, "transform":
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

## Pipeline, clipping and exports

- `sce/pipeline.py` — the report sequence shared by the CLI and `api/main.py`:
  `build_aoi`, `fetch_layers` (osmnx layers run serially because osmnx settings
  are global; the rest run in threads), `analyse`, `run_report`, and the
  `EXPORTERS` table. A new export format is one writer in `sce/export/` with the
  signature `write_x(path, layers, aoi) -> Path` plus one `EXPORTERS` entry; the
  CLI `--export` choices and the web API pick it up from there.
- `sce/clip.py` — `clip_layers(layers, outer, inner)`: geometry only (clip,
  window and mask, truncate the street graph), then the named provider's
  `summarise` for the inner square. No per-layer rules here.
- `sce/site.py` — `Site`: one padded fetch (`Site.load`, fetch injected), one
  clip per square (`layers_for`, with building use attached), and the views the
  web app needs: `analyse`, `preview`, `climate`, `export`. The API is HTTP only;
  test site behaviour through `Site` with fixture layers
  (`tests/unit/_site_fixtures.py`).
- `sce/vocab.py` — the only land-use, building-use and height-source vocabulary.
  Providers emit it, metrics/exports/sheet key on it, and the web app's
  `web/lib/vocab.generated.ts` is generated from it
  (`python -m sce.vocab --ts > web/lib/vocab.generated.ts`; a test fails when stale).
- `sce/heights.py` — fills missing building heights from a per-building-resolution
  height raster (EA LiDAR nDSM). Never fills a building it cannot measure.
- Shared helpers: `sce/export/_contours.py` (one contour implementation for every
  vector format) and `sce/export/_georef.py` (CRS and local-origin sidecar).
- OSM providers call `configure_osmnx(cache)` and wrap queries in
  `with_overpass_fallback(...)` from `sce/providers/_overpass.py`.

## Web app

`api/main.py` (FastAPI, `pip install -e ".[web]"`) and `web/` (Next.js). The API
verifies Clerk session JWTs unless `SCE_AUTH_DISABLED=1` (local development only).
Web checks run in CI as their own job: `npm run typecheck`, `lint`, `test`, `build`.

## Style

Type hints, `from __future__ import annotations`, no comments that restate the
code, docstrings that explain *why*. Line length 110 (ruff; CI also runs `ruff format --check`). No new dependencies
without saying so. Prefer stdlib and what is already installed:
osmnx 2.1.1, geopandas 1.1.4, shapely 2.x, pyproj, rasterio 1.5.1, matplotlib,
numpy, pandas, requests, networkx, pyarrow, ezdxf 1.4.4, click. Optional extras:
`[rhino]` rhino3dm, `[mesh]` trimesh + mapbox-earcut, `[web]` fastapi, uvicorn, pyjwt.

## Tests

Tests go in `tests/unit/`. Tests that hit the network go in `tests/live/`,
marked `@pytest.mark.live`, and are excluded from a plain `pytest` run. Zero network in unit tests. Use synthetic geometry
with analytically known answers wherever possible (e.g. a perfect 1 km grid has
orientation order phi = 1.0). Do not snapshot floats you have not reasoned about.
