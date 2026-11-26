# Quadrat

Quadrat takes a square of ground anywhere on earth and describes it from open
data: buildings, streets, land use,
terrain, land cover, climate and, in Great Britain, planning constraints. It
computes urban metrics (floor space index, ground space index, street and block
structure, land use mix, slope, degree days, solar and wind) and writes them out
as an A3 PDF sheet and as CAD and GIS files. It is aimed at architects, urban
designers and planners who need a quick, repeatable site analysis at the start of
a project. Everything it reads is free to use and needs no API keys.

The name is the ecologist's quadrat: a square frame laid on the ground to sample
what is inside it. The Python package and command line tool are called `sce`
(the site context engine), and the PDF it produces is the site context report.

It ships three ways to use it:

- a command line tool, `sce`;
- a Python package, `sce`, if you want the layers and metrics in your own code;
- a private web app (FastAPI in `api/`, Next.js in `web/`) where you drag a square
  on a map and watch the analysis update.

## Quick start

Requires Python 3.12 or newer (CI runs 3.12, 3.13 and 3.14). Pure pip: no conda,
no system GDAL.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,rhino,mesh,web]"   # everything; see "Install options" below
```

### Command line

Coordinates are `lon,lat` in decimal degrees. `--radius` is the half-width of the
square in metres.

```bash
sce report --coords -0.1276,51.5074 --name london --radius 1200 \
           --export gpkg --export dxf
```

This writes into `out/`: the A3 sheet `london.pdf`, the dossier
`london.dossier.json`, and the GeoPackage and DXF. The first run for a site
fetches data over the network (about a minute) and caches it; later runs are
fast. `sce report --help` lists every option.

Other commands:

```bash
sce compare tashkent=69.2401,41.2995 london=-0.1276,51.5074 --radius 1200
sce providers      # every data provider, its layer, rank and licence
sce attribution    # regenerate ATTRIBUTION.md from the provider registry
```

`sce compare` puts two to four sites on one A3 sheet (`out/compare.pdf`) with every
figure-ground drawn at the same scale. It normalises but deliberately does not
score or rank: weighting one site against another is the client's judgement, and
a test enforces that no row declares a preferred direction.

### Web app, locally

Terminal 1, from the repo root (API on port 8000, authentication off):

```bash
SCE_AUTH_DISABLED=1 uvicorn api.main:app --port 8000
```

Terminal 2:

```bash
cd web
npm install
npm run dev        # http://localhost:3000
```

In development Next.js proxies `/api/*` to `127.0.0.1:8000`. With no Clerk keys
set the app runs without sign-in and shows a "Dev mode" pill. Check the API with
`curl localhost:8000/api/health`. More in [web/README.md](web/README.md).

### Install options

| Command | Adds |
|---|---|
| `pip install -e ".[dev]"` | CLI, pytest, ruff, httpx |
| `pip install -e ".[rhino]"` | `.3dm` export (rhino3dm) |
| `pip install -e ".[mesh]"` | `.glb` and `.obj` export (trimesh, mapbox-earcut) |
| `pip install -e ".[web]"` | FastAPI, uvicorn, PyJWT for `api/` |
| `pip install -e ".[overture]"` | Overture Maps buildings fallback (pyarrow). Not on the hosted API |

## Data sources

All sources are free and keyless. Run `sce providers` for the live list; the
full licence text per source is in [ATTRIBUTION.md](ATTRIBUTION.md), which is
generated from the provider registry rather than written by hand.

| Layer | Source | Licence | Coverage |
|---|---|---|---|
| Buildings | OpenStreetMap (Overpass), then Overture Maps (needs `sce[overture]`), then map tiles | ODbL | Global |
| Streets, land use, amenities | OpenStreetMap | ODbL | Global |
| Building heights (fallback) | Global Human Settlement Layer (GHSL) | CC BY 4.0 | Global, about 100 m |
| Building heights (measured) | Environment Agency 1 m LiDAR | OGL v3.0 | England only |
| Terrain | Copernicus GLO-30 | ESA COPDEM licence | Global; a surface model, not bare earth |
| Terrain, bare earth (opt-in) | FABDEM, via `--dtm fabdem` | CC BY-NC-SA 4.0 | Global; non-commercial, tiles supplied by you |
| Land cover | ESA WorldCover | CC BY 4.0 | Global |
| Climate | ERA5 reanalysis via Open-Meteo | CC BY 4.0 | Global; Open-Meteo's free tier is non-commercial |
| Planning constraints | planning.data.gov.uk | OGL v3.0 | England only |

Two conditions are enforced in code. The GeoPackage and DXF exports carry
OpenStreetMap-derived geometry and are therefore subject to ODbL share-alike
when you redistribute them. Any non-commercial source is skipped unless you opt
in, and its licence is then printed on the sheet.

The MIT licence in [LICENSE](LICENSE) covers this source code only. Data the tool
retrieves keeps its own terms.

OSM queries fall back across several Overpass servers, because the main public one
often answers "at capacity". Override the list with `SCE_OVERPASS_URLS`
(comma-separated).

In the web app, buildings, streets, land use and amenities are first drawn within a
couple of seconds from OpenFreeMap vector tiles (OpenMapTiles schema), flagged as
drafts, and replaced by the Overpass result when it arrives. If Overpass has not
answered within `SCE_OVERPASS_BUDGET_S` seconds (default 90) or fails, the tile layers
become the final result, marked approximate in the layer notes.

## Output formats

The PDF sheet and the dossier are always written (the sheet can be skipped with
`--no-sheet`). Other formats are requested with `--export` (repeatable) in the CLI
or ticked in the web app's download panel, which returns them as one ZIP.

| `--export` | File | What it is |
|---|---|---|
| always | `<site>.pdf` | A3 landscape vector sheet, figure-ground dominant |
| `json` / always | `<site>.dossier.json` | Every metric, source, licence, retrieval date and git SHA |
| `gpkg` | `<site>.gpkg` | Layered GeoPackage in the site's metric CRS, plus QGIS `.qml` styles. Written by a built-in sqlite3 writer, no GDAL needed |
| `dxf` | `<site>.dxf` | Real-world metres, layered for AutoCAD, Rhino, Revit, Vectorworks |
| `3dm` | `<site>.3dm` | Rhino model: buildings with known heights as solids, the rest as flat curves (needs `[rhino]`) |
| `svg` | `<site>.svg` | Plan drawing, 1 unit = 1 m, one group per CAD layer |
| `geojson` | `<site>.geojson` | Every layer in WGS84, with height and height source per building |
| `glb`, `obj` | `<site>.glb`, `.obj` | 3D mesh: terrain with buildings on it (needs `[mesh]`) |
| `epw` | `<site>.epw` | EnergyPlus weather file (typical meteorological year) |
| `png` | `<site>.png` | The sheet as a raster image |
| `compare` command | `compare.pdf` | Two to four sites at one shared scale |

The web app also writes `georef.json` and a short README into each ZIP; they
record the CRS and local origin that the mesh and CAD files use.

## How it works

```
sce/             the engine (Python package)
  aoi.py           the square of interest and its single metric CRS
  site.py          Site: one padded fetch, then clip, analyse, preview, climate, export
  pipeline.py      fetch layers, compute metrics, write exports (CLI and API share it)
  registry.py      provider registry with fallback between sources
  clip.py          clip fetched layers to a smaller square
  vocab.py         the one vocabulary for land use, building use and height source
  providers/       one module per data source
  metrics/         FSI, GSI, streets, land use, terrain, climate, access
  export/          one writer per output format
  report/          the A3 sheet and compare sheet
  cli.py           the `sce` command
api/main.py      FastAPI: Clerk JWT auth, SSE /api/load, analyse, preview, climate, export
web/             Next.js 16 app: MapLibre map, panels, charts, sun path and wind rose
tests/           unit (offline), meta (contracts), live (network, opt-in)
```

A web request flows like this. The browser asks `/api/load` for a padded area
around the square; the API builds an `sce.Site`, which asks the registry for each
layer, and the registry tries providers in rank order until one has coverage.
Moving or resizing the square inside that area calls `analyse` and `preview`,
which clip the loaded layers and recompute in under a second. Download calls
`export`, which runs the chosen writers and zips the files. The CLI uses the same
pipeline without the web layers.

API endpoints (all under `/api`): `GET /health`, `POST /load` (server-sent
events with progress), `POST /analyse`, `POST /preview`, `POST /climate`,
`POST /export`. The first placement takes about a minute when nothing is cached.

Vocabulary shared with the web app is generated, not duplicated:
`python -m sce.vocab --ts > web/lib/vocab.generated.ts`.

### Notes on method

- **Projection.** One metric CRS is chosen per site: UTM from the centroid, or
  an equal-area projection when the site crosses a zone boundary or sits above
  80 degrees latitude. Every metric rejects geographic (degree) input, and a
  test asserts it.
- **Heights are labelled by source.** Building heights come from OSM `height` or
  `levels` tags (storeys times 3 m), with gaps measured from LiDAR in England. Where
  OSM heights cover under 40% of footprints, FSI is derived from GHSL and says
  so; where nothing is available it is withheld. The Rhino model draws the same
  line: known heights become solids, the rest stay flat.
- **Terrain is a surface model.** Copernicus GLO-30 includes rooftops and tree
  canopy. Slope is computed after reprojecting to a metre grid, never on degrees.
- **Footprints are unioned, not summed**, so overlapping traced buildings cannot
  push ground space index above 1.0.
- **Parcels are not open globally.** Block area, from polygonising the street
  network, is the proxy.
- **Street orientation order** follows Boeing (2019), normalised to 0 to 1.
- **Climate is regional.** ERA5 snaps to a grid near 3 km; the sheet records the
  offset to the grid point used.

## Deployment

`vercel.json` deploys the repo as one Vercel project using Vercel Services: `web/`
as the Next.js service and `api/main.py` as the Python service, with `/api/*`
routed to Python and everything else to Next.js. Access is private through
[Clerk](https://clerk.com) with sign-up set to Restricted (invitation only); the
API verifies the Clerk session token on every call. Environment variables and
step-by-step setup are in [web/README.md](web/README.md#deploy).

## Testing

```bash
pytest                      # about 457 offline tests, no network
pytest -m live              # opt-in tests against the real data services
ruff check . && ruff format --check .

cd web
npm run typecheck && npm run lint && npm test && npm run build
```

Metrics are checked against analytically known answers rather than snapshots: a
perfect grid must give orientation order 1.0, overlapping squares must give the
union area, a 1:20 plane must give 2.862 degrees. Live tests assert physical
bounds (Riyadh is dry, London needs heating), skip when a host throttles, and
run weekly in CI. CI (`.github/workflows/ci.yml`) runs pytest and ruff on Python
3.12 to 3.14, and the web checks on Node 24.

## Limitations

- **Planning constraints and measured LiDAR heights are England only.** Elsewhere
  those layers are absent and the sheet says so.
- **Data quality follows OpenStreetMap.** Over much of Central Asia and the Gulf
  OSM land use is sparse; the sheet shows the unmapped share and puts ESA
  WorldCover beside it. Building heights are often missing worldwide, hence the
  fallbacks above.
- **Open-Meteo's free tier is non-commercial.** Check its terms before using the
  climate layer in paid work.
- **Climate is regional ERA5, not site microclimate.** Coastal and mountain sites
  are the weakest cases.
- **FABDEM is never fetched for you.** It is published as whole 10-degree
  archives, so the provider reads tiles you have downloaded and licensed.
- **Size limits.** The CLI refuses a radius above 5 km without `--force`; the web
  app limits the square to 2 km wide.
- **Loaded sites are cached per server instance.** On serverless a request may
  land on a different instance; the API then answers 409 and the UI reloads the
  site.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the provider, metric and export
contracts and the traps they exist to prevent.
