import { metresPerDegree, squarePolygon, type SquareState } from "./square";
import type { Preview } from "./types";

/** Buildings are drawn this far outside the square as context; must match CONTEXT_RING_M on the server. */
export const CONTEXT_RING_M = 150;

type Box = [number, number, number, number]; // west, south, east, north

function boxOf(s: SquareState, extraM = 0): Box {
  const m = metresPerDegree(s.lat);
  const dLon = (s.halfWidthM + extraM) / m.lon;
  const dLat = (s.halfWidthM + extraM) / m.lat;
  return [s.lon - dLon, s.lat - dLat, s.lon + dLon, s.lat + dLat];
}

const inside = (b: Box, x: number, y: number) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
const intersects = (a: Box, b: Box) => a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];

function walk(c: unknown, acc: Box): void {
  if (Array.isArray(c) && typeof c[0] === "number") {
    const [x, y] = c as number[];
    if (x < acc[0]) acc[0] = x;
    if (y < acc[1]) acc[1] = y;
    if (x > acc[2]) acc[2] = x;
    if (y > acc[3]) acc[3] = y;
  } else if (Array.isArray(c)) for (const x of c) walk(x, acc);
}

/** Bounding box of a feature's geometry, or null when it has none. */
function bboxOf(f: GeoJSON.Feature): Box | null {
  const g = f.geometry as { coordinates?: unknown } | null;
  if (!g?.coordinates) return null;
  const acc: Box = [Infinity, Infinity, -Infinity, -Infinity];
  walk(g.coordinates, acc);
  return Number.isFinite(acc[0]) ? acc : null;
}

const centreOf = (b: Box): [number, number] => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

const collection = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });

function crossing(fc: GeoJSON.FeatureCollection | undefined, sq: Box): GeoJSON.FeatureCollection | undefined {
  if (!fc) return fc;
  return collection(
    fc.features.filter((f) => {
      const b = bboxOf(f);
      return b !== null && intersects(b, sq);
    }),
  );
}

/**
 * A preview for `to`, cut from the last full preview (drawn for `from`) without asking the server.
 * Applies only when `to` lies inside the loaded extent, the old square plus its context ring;
 * otherwise null and the caller waits for the server. Buildings are split by centroid, so a
 * building in the old ring can become a building (or the reverse). Other layers keep whole
 * features that touch the new square; the server's answer replaces all of this shortly.
 */
export function subsetPreview(full: Preview, from: SquareState, to: SquareState): Preview | null {
  const extent = boxOf(from, CONTEXT_RING_M);
  const sq = boxOf(to);
  if (!(sq[0] >= extent[0] && sq[1] >= extent[1] && sq[2] <= extent[2] && sq[3] <= extent[3])) return null;
  const ring = boxOf(to, CONTEXT_RING_M);

  const buildings: GeoJSON.Feature[] = [];
  const context: GeoJSON.Feature[] = [];
  for (const f of [...full.buildings.features, ...(full.context?.features ?? [])]) {
    const b = bboxOf(f);
    if (!b) continue;
    const [x, y] = centreOf(b);
    if (inside(sq, x, y)) buildings.push(f);
    else if (inside(ring, x, y)) context.push(f);
  }
  return {
    ...full,
    square: squarePolygon(to),
    buildings: collection(buildings),
    context: collection(context),
    streets: crossing(full.streets, sq) ?? collection([]),
    landuse: crossing(full.landuse, sq),
    contours: crossing(full.contours, sq),
    constraints: crossing(full.constraints, sq),
  };
}
