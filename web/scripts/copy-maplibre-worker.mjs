// MapLibre v6 loads its web worker from a URL next to its own module. Next's
// bundler moves that module into a chunk, so the relative worker URL 404s.
// Copy the self-contained worker into public/ and point MapLibre at it
// (see setWorkerUrl in components/MapView.tsx).
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("maplibre-gl/dist/maplibre-gl.css"));
mkdirSync("public/maplibre", { recursive: true });
copyFileSync(join(dist, "maplibre-gl-worker.mjs"), "public/maplibre/maplibre-gl-worker.mjs");
console.log("copied maplibre-gl-worker.mjs -> public/maplibre/");
