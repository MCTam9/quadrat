# Site Context Report

Coordinates and a radius, anywhere on earth, to an A3 sheet and machine-readable
data: urban morphology, terrain, land cover, climate, accessibility and, where
the data exists, statutory planning constraints.

```bash
sce report --coords 69.2401,41.2995 --name tashkent --radius 1200 \
           --export gpkg --export dxf
```

The same command runs in Tashkent, London and Riyadh. Nothing about the
invocation changes; the London sheet simply carries a Conservation Area boundary
because that data exists in Great Britain and not in Uzbekistan.

I did this analysis by hand once, on a 111,800 m² masterplan in Shanghai. It
now runs in about a minute, anywhere.

## What comes out

| File | What it is |
|---|---|
| `<site>.pdf` | A3 landscape vector sheet, figure-ground dominant |
| `<site>.dossier.json` | Every metric, every source, licence and retrieval date, git SHA |
| `<site>.gpkg` | Layered GeoPackage in the site's metric CRS, with QGIS styles |
| `<site>.dxf` | Real-world metres, layered for AutoCAD, Rhino, Revit and Vectorworks |

## Verified on three continents

Run on 2026-09-06 at a 1,200 m radius, no code changes between sites.

| | Tashkent | London | Riyadh |
|---|---|---|---|
| Projection chosen | EPSG:32642 | EPSG:32630 | EPSG:32638 |
| Intersections per km² | 198 | 245 | — |
| Mean street segment | 52 m | 27 m | — |
| Ground space index | 0.20 | 0.40 | 0.44 |
| Floor space index | withheld, 10% height coverage | 1.18 | withheld, 1% height coverage |
| Median block | 0.25 ha | 0.40 ha | — |
| Heating degree days | 2,183 | 2,335 | 210 |
| Cooling degree days | 1,382 | 126 | 3,696 |
| Annual solar, kWh/m² | 1,669 | 1,136 | 2,116 |
| Prevailing wind | NW | SW | — |
| OSM land use coverage | 91% | 40% | 8% |

The last row is why the tool reads ESA WorldCover as well as OpenStreetMap. Over
much of Central Asia and the Gulf, OSM land use is close to absent, and a single
mix statistic computed over mostly unmapped ground is precisely wrong. The sheet
shows the unmapped share explicitly and puts the satellite land cover beside it.

## What it does that the alternatives do not

Firms already buy CAD extracts, run browser-based massing analysis, or spend an
analyst-day per bid in QGIS. This does something narrower and more repeatable.

- **Works everywhere, not just where a vendor has coverage.** Same command in
  Tashkent as in London.
- **Prints its own provenance.** Every sheet carries the projection, the sources,
  their licences and the date each was retrieved, plus the commit that drew it.
- **Refuses to guess.** Floor space index is withheld, with the coverage stated,
  whenever building height data covers less than 40% of footprints. Land use
  shows an explicit unmapped slice.
- **Is a pipeline, not a picture.** The dossier and GeoPackage carry everything
  the drawing shows, so the output is an input to something else.
- **No composite score.** The compare mode normalises but does not rank.
  Weights belong to the client, not the tool.

## Notes on method

**Projection.** One metric CRS is chosen once per site and stamped on the area of
interest: UTM from the centroid, or a centroid-centred equal-area projection when
the site crosses a zone boundary or sits above 80° latitude. Every metric calls a
guard that rejects geographic input, and a test asserts that every registered
metric raises on degrees. A 1 km site measures exactly 4,000,000 m² at 60° north,
where a degrees-based buffer would be visibly wrong.

**Terrain is a surface model, not bare earth.** Copernicus GLO-30 includes
rooftops and tree canopy. That is immaterial for a greenfield site and material
in a dense city, so the sheet says which it is. Elevation windows are read by
HTTP range request and reprojected to a square metre grid *before* slope is
computed; slope on a raw geographic raster is the invisible version of the
degrees-as-metres error.

**Footprint areas are unioned, not summed.** Overlapping traced footprints would
otherwise push ground space index above 1.0. Land use classes are allocated
disjointly for the same reason, so the bar is a true partition of the site.

**Parcel grain is not open globally.** Block area, derived by polygonising the
street network, is the proxy. Blocks clipped by the frame are excluded.

**Street orientation order** follows Boeing (2019), normalised to 0–1 so a
perfect grid reads 1.0. The entropy agrees with osmnx's own implementation to
0.0007 nats.

**Climate is regional, not site microclimate.** ERA5 snaps to a grid near 3 km;
the sheet records the offset between the site and the grid point actually used.

## Install

```bash
pip install -e ".[dev]"
```

Pure pip on Python 3.12–3.14. No conda, no system GDAL.

## Tests

```bash
pytest
```

234 tests, zero network. Metrics are checked against analytically known answers
rather than snapshots: a synthetic perfect grid must return orientation order
exactly 1.0, two overlapping squares must produce the union area, a plane at
exactly 1:20 must return 2.862°. A weekly job exercises the live interfaces so
the coverage claims above are machine-checked rather than asserted.

## Licences

Every source is free to use. Two conditions matter and both are enforced in
code: the GeoPackage and DXF exports carry OpenStreetMap-derived geometry and
are therefore subject to ODbL share-alike, and any non-commercial source is
skipped unless explicitly opted into, with its licence printed on the sheet.
See [ATTRIBUTION.md](ATTRIBUTION.md), which is generated from the provider
registry rather than maintained by hand.

## Roadmap

Bare-earth terrain via FABDEM behind an opt-in flag, since it is
non-commercial. Global Wind Atlas for coastal and mountain sites where ERA5 is
too coarse. Population density from the Global Human Settlement Layer. Building
height fallback from GHS-BUILT-H so floor space index survives thin OSM height
coverage. Configurational street metrics via momepy. Speckle export.
