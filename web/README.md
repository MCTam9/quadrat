# Quadrat web app

Next.js 16 frontend for the `sce` API: search a place, drag and resize a square on a MapLibre map, watch live site
analysis, preview buildings coloured by height provenance, read climate charts with sun path and wind rose overlays
(including a 3D sun dome), then download a CAD/GIS bundle as a ZIP.

This file covers the web app only. For what `sce` is, the data sources, output formats and the Python side, see the
[root README](../README.md).

Everything is free to use: OpenFreeMap tiles, Photon geocoding, no API keys. Only Clerk (free tier) is needed for
private deployments.

## Develop

From the repo root, start the API with auth off (see the root README for installing the Python extras):

```sh
SCE_AUTH_DISABLED=1 uvicorn api.main:app --port 8000
```

Then in `web/`:

```sh
npm install
npm run dev        # http://localhost:3000
```

In development `next.config.ts` rewrites `/api/*` to `http://127.0.0.1:8000`. In production no rewrite is applied; the
Python service is served on the same origin under `/api`.

Scripts: `dev`, `build`, `start`, `lint`, `typecheck`, `test` (vitest). CI runs `typecheck`, `lint`, `test`, `build` on
Node 24. `dev` and `build` first copy the MapLibre worker via `scripts/copy-maplibre-worker.mjs`.

## Environment

Copy `.env.example` to `.env.local`. Leave both keys empty to run without auth.

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Enables Clerk. Unset = auth disabled (a "Dev mode" pill is shown). |
| `CLERK_SECRET_KEY` | Server-side Clerk key (needed with the publishable key). |
| `NEXT_PUBLIC_CLERK_SIGN_IN_URL` | Sign-in route, `/sign-in` in the example file. |

With Clerk on, the whole app requires sign-in and shows only `<SignIn/>` at `/sign-in`. Every API call carries
`Authorization: Bearer <session token>`. The API side needs its own variables; see Deploy.

## Layout

- `app/` routes: the picker page and `sign-in`. `proxy.ts` is the Clerk middleware (a no-op without a key).
- `components/` UI: `Picker.tsx` orchestrates; `MapView.tsx` is the MapLibre map with GeoJSON-source handles;
  `SitePanel.tsx`, `Cards.tsx`, `SquareCard.tsx`, `Schedule.tsx` the analysis panels; `ClimatePanel.tsx` the Climate
  tab (fed by `POST /api/climate`); `LayersControl.tsx`, `SkyOverlay.tsx` (sun path / wind rose on the map),
  `Sky3D.tsx` (3D sun dome and wind ring), `ExportPanel.tsx`, `Search.tsx`, `charts/`.
- `lib/` logic, mostly with tests alongside: `square.ts` square geometry, `coords.ts` coordinate parsing,
  `gestures.ts` trackpad gestures, `api.ts` fetch and SSE client, `layers.ts` colour modes and overlays,
  `buildings.ts` height-source mapping, `climate.ts` wind-rose binning and comfort counts, `sun.ts`, `sunpath.ts`
  and `sundome.ts` sun geometry, `export.ts`, `theme.ts`, `blueprint.ts`.

## Notes

- Backend `height_source` values: `height` (tag), `lidar`, `levels` (storeys x 3 m), `unknown`. The vocabulary (land
  use, building use, height source) lives in `lib/vocab.generated.ts`, generated from `sce/vocab.py`. Never edit it by
  hand; regenerate from the repo root with `python -m sce.vocab --ts > web/lib/vocab.generated.ts` (a Python test
  fails when it is stale).
- Export format ids sent to the API: `dxf`, `3dm`, `svg`, `geojson`, `glb`, `obj`, `gpkg`, `epw`.
- The square is limited to 100 m to 2 km wide (the API enforces the same bounds).
- The design is a drawing sheet: white, black ink, one red line for the site. Dark mode is the blueprint (`#12304F`,
  white ink); the basemap (OpenFreeMap positron or dark, retinted) and the panel follow `prefers-color-scheme` live.
- The preview's `context` buildings (a ring outside the square) are drawn as pale massing; without them the map
  still works.

## Deploy

`vercel.json` at the repo root deploys `web/` and the FastAPI app as one project using Vercel Services (beta).
`/api/*` goes to the Python service and everything else to Next.js.

1. `vercel link` from the repo root (the project is `quadrat`).
2. Add Clerk from the Vercel Marketplace (`vercel integration add clerk`, free plan). It creates the Clerk
   application and sets `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` for every environment.
   In the Clerk dashboard, under **Restrictions**, set sign-up mode to **Restricted** (invitation only; free,
   unlike the allowlist) and invite people from **Users > Invitations**.
3. The API needs nothing else for auth: it reads Clerk's issuer and key URL from the publishable key, and on
   Vercel it accepts tokens only from this deployment's own URLs. Override with `CLERK_ISSUER`, `CLERK_JWKS_URL`
   or `CLERK_AUTHORIZED_PARTIES` (comma-separated origins, checked against the token's `azp` claim) if you use a
   custom Clerk domain or call the API from elsewhere.
   - `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` if the build says the Python bundle is too large.
   - The Python bundle is about 450 MB after `scripts/trim_site_packages.py` (it was ~670 MB before pyogrio and
     pyarrow were dropped), under Vercel's 500 MB standard limit. The hosted API has no Overture fallback
     (`sce[overture]` is CLI-only); buildings fall back from OSM to map tiles.
   - Optional: `SCE_CORS_ORIGINS` (comma-separated) if the API is called from another origin.
4. Connect the GitHub repo (`vercel git connect`) so pushes deploy, or run `vercel deploy` for a preview.
   Check `/api/health`, then sign in and load a site.

Do not set `SCE_AUTH_DISABLED=1` in production.

Limits: 300 s per request by default (Pro can raise it to 800 s) (a cold site load takes about a minute), 2 GB memory, one region. Fetched data is
cached in each instance's `/tmp`. If a later request lands on a different instance, the API answers 409 and the UI
reloads the site transparently.
