# Site Context Report — the demo asset, redirected

## Context

The alternate-channels plan is built and running: cold outreach (Phase 7), the
recruiter pack, niche job boards and the events shortlist all shipped, 435 tests
pass. **One thing still blocks the whole outreach channel:**
`config/outreach.yaml` has `demo_url: ""` and `lint_email.py` refuses any email
without a link.

That demo was going to be **Planning Radar** (UK planning applications → BD leads
for small London residential practices). Vincent has correctly killed it:

- **Cross Works is a cross-disciplinary design *and technology* firm** — London,
  Riyadh, Tashkent; 28 countries; GIS specialists, computational designers and
  software engineers alongside masterplanners; currently masterplanning a
  ~25,000 ha new city for the Uzbek government. A tool that finds householder
  loft conversions in Southwark misreads what they are.
- **Divercity** works across the UK, Europe, North Africa, the USA and South America.
- The tracker shows the commercial stake: Cross Works was **"Design technologist
  / computational designer", £45–50k, Closed** (not rejected); Divercity was
  **£35–38k Part II, Rejected**. Both reached interview. The urban/computational
  track is worth ~£10k more.

So the demo must be **internationally portable and urban-scale**. Vincent asked
for the highest-impact, most time-saving option that generalises across firms,
built once with two written framings.

## What to build

**Site Context Report.** Coordinates + radius (or a GeoJSON boundary) **anywhere
on earth** → an A3 sheet plus machine-readable data: urban morphology, terrain,
climate, accessibility. A compare mode benchmarks candidate sites side by side.

Named for what it produces, not what it is. "Intelligence engine" is startup
language; architects hear marketing.

**Why this option:** it is the only one that serves every target at once (Cross
Works, Divercity, AEC-tech firms, and small London practices via the UK
constraints provider); the time it saves is real and repeated, because early
site/context analysis is redone from scratch on every project and every bid; and
the narrative is already his — he *"conducted contextual urban-grain analysis for
the Yuyuan Phase 2 masterplan (collaborating with Bjarke Ingels Group)"*,
111,800 m² GFA, by hand, in Shanghai. *I did this by hand on a 111,800 m²
masterplan. Now it runs in a minute, anywhere.*

## Verified live, 2026-08-14

| Source | Verified |
|---|---|
| **Overpass (OSM)** | Tashkent 4×6 km = **15,242 buildings**; Riyadh 2×2 km = 2,720; London = 17,741. Rate limit measured: **2 slots** → serial only. |
| **Copernicus GLO-30 DEM** (AWS COG) | HTTP **206** range reads on both London and Tashkent tiles, no auth. **This is the terrain spine.** |
| **Open-Meteo archive** | Keyless, global; hourly `wind_direction_10m` → wind rose. Snaps to the ERA5 grid (~3 km). |
| **MS GlobalMLBuildingFootprints** | Live, vintage 2026-02, 30,344 tiles, covers **Uzbekistan, Saudi Arabia, UK** — the thin-coverage fallback. |
| **planning.data.gov.uk** | OGL v3.0 constraint geometry (UK only). |
| **Wheels on Python 3.14.5** | shapely 2.1.2, pyproj 3.7.2, rasterio 1.5.1 all ship cp314; pyogrio ships cp311-abi3; geopandas/osmnx pure-Python. **`pip install` just works** — no conda, no Homebrew GDAL. |

Tashkent's OSM density is comparable to London's. That was the biggest risk and
it is retired.

## Stack

**Use:** `osmnx` (does the heavy lifting: Overpass querying, slot-aware rate
limiting, HTTP caching, auto-UTM projection, intersection consolidation,
orientation entropy and rose), `geopandas`, `shapely`, `pyproj`, `rasterio` (the
one genuinely new library, ~3 hours, and what makes terrain real), `matplotlib`.

**Do not use:** fiona (drags a second GDAL), conda, folium/contextily (a slippy
map is a worse portfolio artefact than a drawing), PostGIS/FastAPI, momepy
(right library, would eat two days — name it in the README roadmap instead).

## Architecture — pluggable providers

The provider seam *is* the systems-design story, and it is what makes the UK work
reusable rather than wasted.

```
sce/
  aoi.py            the CRS spine; everything depends on it
  registry.py       layer -> ordered provider chain, fallback + override
  cache.py          content-addressed, .meta.json sidecars (url/time/licence)
  coverage.py       OSM sufficiency -> degraded flag
  providers/        osm_streets, osm_buildings, osm_landuse, osm_amenities,
                    ms_buildings (fallback), terrain_copernicus,
                    climate_openmeteo, uk_constraints
  metrics/          street, fabric, landuse, access, terrain, climate
  report/           style, figures, sheet (A3 GridSpec), compare
```

Each provider declares `name, layer, licence, rank`, an `available(aoi)` and a
`fetch(aoi, cache) -> LayerResult` returning geometry **already in the metric
CRS**. `uk_constraints.available()` is True only inside GB, so a Conservation
Area / Article 4 block appears on the London sheet and not the Tashkent one.
Same command, richer where richer data exists — that is the demo moment.

## Metrics — chosen for meaning

**Keep:** consolidated intersection density (not raw node density), street length
density, mean segment length, dead-end share, **orientation order φ normalised
0–1** (osmnx returns nats, which mean nothing to a reader) plus the rose, median
block area + IQR via `polygonize`, ground space index and median footprint,
FSI **only when height-tag coverage > 40%** (otherwise print the coverage), a
10-minute walk reach ratio, amenity *categories* reachable, mean slope and % of
area under 1:20, and degree days / GHI / wind rose.

**Cut:** circuity (near-constant across real cities), k_avg and other telemetry,
raw POI counts (measures mapper enthusiasm), population grids (a day and 100 MB).

**Correction worth noting:** land-use mix *entropy* is cut. OSM `landuse` coverage
is near-absent across much of Central Asia and the Gulf, so an entropy scalar
over 60% unmapped area is precisely wrong, and a Cross Works GIS specialist would
ask exactly that. Replace with a stacked bar **including an explicit "unmapped"
slice**, greyed below 50% coverage. Showing the completeness problem is the more
impressive move than hiding it in a scalar.

State one limit out loud: **parcel grain is not open globally**, so block size is
the proxy.

## CRS — the part that must be unassailable

One metric CRS per site, chosen once, stamped on the AOI, **enforced by a test**.
UTM from the AOI centroid by default; centroid-centred LAEA when the AOI crosses
a zone boundary or above 80°. `assert_metric_crs()` at the top of every metric,
and a parametrised test asserting **every registered metric rejects EPSG:4326** —
same shape as his existing `tests/meta/test_tool_conventions.py`.

Traps that bite: buffer the *projected* centre, never degrees; `graph_from_point`
returns a square, so clip and use the same area denominator everywhere;
`make_valid` then `union_all()` before any footprint area sum or **coverage
exceeds 1.0** in dense blocks, the most visible possible embarrassment; reproject
the DEM window to a square 30 m grid **before** computing slope, because slope on
a raw geographic raster is the invisible version of the degrees-area error; and
note GLO-30 is a **DSM not a DTM** (includes rooftops) — immaterial for a
greenfield masterplan site, which is exactly the Tashkent case.

Print the EPSG in the title block.

## Build order (5–7 days)

- **Day 0 (1–2 h): spike, don't build.** Install the stack, run `graph_from_point`
  on Tashkent, `basic_stats`, `plot_orientation`, one Copernicus window. Learn on
  Day 0, not Day 4.
- **Day 1: the spine.** `aoi.py` complete *with its test file*, cache, registry,
  OSM street/building providers. CRS work finishes today and is never revisited.
- **Day 2: metrics** + block polygonisation + synthetic-grid known-answer tests.
  **Also `--export gpkg`** — a layered GeoPackage, correctly projected, that
  opens in QGIS. This lands with exactly the person evaluating him.
- **Day 3: terrain + climate.** Freeze fixtures the moment each provider works.
- **Day 4: the sheet.** A full day. Get one site right before adding panels.
- **Day 5: access + compare + polish.** Print it on paper; fix what's ugly.
- **Day 6: hardening.** MS fallback, `coverage.py`, `uk_constraints.py`, CI, README.
- **Day 7: ship.** Triptych README, 90-second recording, and a 300-word **"Notes
  on method"** covering projection choice, DSM-not-DTM and OSM completeness —
  the section a GIS specialist will actually read.

**Cut order if it slips:** MS fallback (keep the coverage warning), wind rose,
compare sheet (emit a table), climate chart, locator inset, isochrone (keep
distance-to-transit). If it slips badly, **ship two sites — Tashkent and London**.
**Never cut:** the metric-CRS spine, the figure-ground, the provenance title
block, the offline tests.

## Output

**A3 landscape vector PDF**, one page per site: figure-ground dominant (with a
graphic scale bar drawn from the metric CRS — the detail that says *drawing* not
*plot*), orientation rose above wind rose (the pairing that lets someone say
"this grid sits 40° off the prevailing wind"), hillshaded terrain, a climate
strip, and a sectioned metrics table set with `ax.text`, not `ax.table`. Title
block carries coordinates, AOI area, **EPSG**, sources with retrieval dates,
licences, version and git SHA.

Also emit `dossier.json` with full provenance — that is what says *pipeline, not
picture* to Speckle or Sensat.

Compare mode uses **identical scale across sites** and a normalised table with no
composite score: weights belong to the client, not the tool. Saying so in the
README is a stronger signal than the feature.

## Tests

Zero network, enforced by an autouse fixture that makes `requests` raise. Point
osmnx's cache at `tests/fixtures/` so the **real code path runs offline**.
Synthetic 1 km grid with analytically known answers (φ = 1.0) proves the metrics
rather than snapshotting them. A provider-contract test catches the next provider
anyone adds. CI on 3.12/3.13/3.14, plus a weekly `live.yml` so the README's
"works today" claim is machine-checked.

## Corrections to my earlier thinking

- **Terrain:** Copernicus GLO-30 COGs, not Open-Elevation. A point API cannot
  give slope or aspect, and reconstructing a surface would take thousands of
  requests.
- **The GLA Planning Datahub does not belong here.** It is a temporal,
  London-only application pipeline — a different product. Keep Planning Radar as
  a separate repo and cross-link. The right UK slot-in is planning.data.gov.uk
  **constraints**, because those are context layers.
- **Demo at 1.5–2 km radius, not 25,000 ha.** That figure is a 15.8 km square; a
  full-extent query is a huge download and the figure-ground becomes a grey
  smudge. Guard `--radius` above ~5 km behind `--force`.
- **No web UI.** It would turn a drawing you can email into a localhost demo, and
  dilute the geospatial claim with a skill nobody doubts he has.

## Gaps this closes, and a truth problem to fix first

- **He has zero evidenced Python geospatial work.** QGIS (desktop) and
  Rhino/Grasshopper terrain are evidenced; geopandas/shapely/osmnx/OSM appear
  nowhere. This build creates that evidence for the roles paying ~£10k more.
- **`demo_url`, `portfolio_url`, `github_url` are all empty.** This fills all three.
- **Fix before re-approaching Cross Works:** his sent letter claimed *"Ladybug,
  ClimateStudio, and Eddy3D"* and an ArcGIS Pro/Enterprise transition, none of
  which appear in `master_profile.json`. Under the repo's own TRUTH gate those are
  unevidenced. Evidence them or never repeat them.
- **Add to the profile:** the RCA thesis was sited in **Morocco** (arid climate,
  compressed earth, QGIS terrain export). Real international, climate-driven,
  terrain evidence that currently survives only in cover letters.

## Verification

- Correct dossier for **three sites on three continents**, no code changes between them.
- Areas spot-checked; the CRS test proves no metric accepts geographic input.
- `pytest` green offline; CI on three Python versions.
- Public repo, MIT, README triptych, `ATTRIBUTION.md` (ODbL share-alike applies to
  the GeoPackage export).
- Loom under two minutes showing the Tashkent run.
- Then set `demo_url`, add the GitHub link to both master CV headers, fill
  `github_url` — and the outreach channel unblocks, warm list first, Cross Works
  leading.
