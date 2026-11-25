# Site picker (web)

Next.js 16 frontend for the `sce` API: search a place, drag and resize a square on the map, watch live site analysis,
preview buildings coloured by height provenance, then download a CAD bundle (ZIP).

Everything is free to use: OpenFreeMap tiles, Photon geocoding, no API keys. Only Clerk (free tier) is optional.

## Develop

From the repo root, start the API (auth off):

```sh
SCE_AUTH_DISABLED=1 uvicorn api.main:app --port 8000
```

Then in `web/`:

```sh
npm install
npm run dev        # http://localhost:3000, /api/* is proxied to 127.0.0.1:8000 in development
```

Scripts: `dev`, `build`, `start`, `lint`, `typecheck`, `test`.

## Environment

Copy `.env.example` to `.env.local`.

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Enables Clerk. Unset = auth disabled (a "Dev mode" pill is shown). |
| `CLERK_SECRET_KEY` | Server-side Clerk key (needed with the publishable key). |

With Clerk on, the whole app requires sign-in. Set sign-up to **Restricted** in the Clerk dashboard for invite-only
access; the UI shows only `<SignIn/>` at `/sign-in`. Every API call carries `Authorization: Bearer <session token>`.

In production, serve the Python API on the same origin under `/api` (no rewrite is applied outside development).

## Layout

- `lib/square.ts` square geometry (tested), `lib/coords.ts` coordinate parsing, `lib/sun.ts`, `lib/buildings.ts`
  (height-source mapping), `lib/api.ts` (fetch + SSE client).
- `components/MapView.tsx` MapLibre map with GeoJSON-source handles; `Picker.tsx` orchestration; `Cards.tsx` panels.
- `proxy.ts` Clerk middleware (no-op without a key).

- `lib/layers.ts` colour modes, overlays, building-type classes, map annotations; `lib/climate.ts` wind-rose binning,
  temperature colour scale, comfort counts; `lib/sunpath.ts` stereographic sun-path geometry.
- `components/LayersControl.tsx`, `SkyOverlay.tsx` (sun path / wind rose SVG on the map), `ClimatePanel.tsx` (Climate tab,
  fed by `POST /api/climate`), `charts/SkyCharts.tsx`.

## Notes

- Backend `height_source` values: `height` (tag), `lidar`, `levels` (storeys x 3 m), `unknown`. Vocabulary (land use, building use,
  height source) comes from `lib/vocab.generated.ts`, generated from `sce/vocab.py`; never edit it.
- Export format ids sent to the API: `dxf`, `3dm`, `svg`, `geojson`, `glb`, `obj`, `gpkg`, `epw`.
- The design is a drawing sheet: white, black ink, one red line for the site. Dark mode is the blueprint (`#12304F`, white ink);
  the basemap (OpenFreeMap positron or dark, retinted) and the panel both follow `prefers-color-scheme` live.
- The preview's `context` buildings (a ring outside the square) are drawn as pale massing; without them the map still works.

## Deploy (free: Vercel Hobby + Clerk free)

`vercel.json` at the repo root deploys `web/` and the FastAPI app as one project using
Vercel Services (beta). `/api/*` goes to the Python service and everything else to Next.js.

1. Create a Clerk application on the free plan. Under **Restrictions**, enable **Restricted** sign-up mode
   (invitation only; this is free, unlike the allowlist). Invite yourself from **Users → Invitations**.
2. `vercel link` from the repo root (Hobby plan, no payment method needed), then set:
   - Web: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`.
   - API: `CLERK_JWKS_URL` (`https://<your-clerk-frontend-api>/.well-known/jwks.json`),
     `CLERK_ISSUER` (`https://<your-clerk-frontend-api>`), `CLERK_AUTHORIZED_PARTIES` (your deployment URL).
   - `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`: the geospatial Python stack may exceed the 500 MB standard bundle.
3. `vercel deploy` for a preview. Check `/api/health`, then sign in and load a site.

Limits on Hobby: 300 s per request (a cold site load takes about a minute), 2 GB memory, one region.
Fetched data is cached in each instance's `/tmp`. If a later request lands on a different instance, the API
answers 409 and the UI reloads the site transparently.
