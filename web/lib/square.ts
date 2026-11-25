export interface SquareState {
  lon: number;
  lat: number;
  halfWidthM: number;
}

export const MIN_HALF_M = 50;
export const MAX_HALF_M = 1000;
export const PRESETS_M = [250, 500, 1000, 2000] as const;

const M_PER_DEG_LAT = 111_320;

export function clampHalf(h: number): number {
  if (!Number.isFinite(h)) return MIN_HALF_M;
  return Math.min(MAX_HALF_M, Math.max(MIN_HALF_M, h));
}

export function metresPerDegree(lat: number): { lon: number; lat: number } {
  return { lat: M_PER_DEG_LAT, lon: M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180) };
}

/** Corner order: NW, NE, SE, SW (closed ring returned by squareRing). */
export function squareCorners(s: SquareState): [number, number][] {
  const m = metresPerDegree(s.lat);
  const dLon = s.halfWidthM / m.lon;
  const dLat = s.halfWidthM / m.lat;
  return [
    [s.lon - dLon, s.lat + dLat],
    [s.lon + dLon, s.lat + dLat],
    [s.lon + dLon, s.lat - dLat],
    [s.lon - dLon, s.lat - dLat],
  ];
}

export function squareRing(s: SquareState): [number, number][] {
  const c = squareCorners(s);
  return [...c, c[0]];
}

export function squarePolygon(s: SquareState): GeoJSON.Feature<GeoJSON.Polygon> {
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [squareRing(s)] },
  };
}

/** Resize symmetrically about the centre: half-width = max of |dx|,|dy| in metres to the pointer. */
export function resizeFromCorner(s: SquareState, pointer: [number, number]): SquareState {
  const m = metresPerDegree(s.lat);
  const dx = Math.abs(pointer[0] - s.lon) * m.lon;
  const dy = Math.abs(pointer[1] - s.lat) * m.lat;
  return { ...s, halfWidthM: clampHalf(Math.max(dx, dy)) };
}

export function moveCentre(s: SquareState, lon: number, lat: number): SquareState {
  return { ...s, lon, lat: Math.max(-85, Math.min(85, lat)) };
}

export function setEdgeLength(s: SquareState, edgeM: number): SquareState {
  return { ...s, halfWidthM: clampHalf(edgeM / 2) };
}

export function edgeLengthM(s: SquareState): number {
  return s.halfWidthM * 2;
}

export function areaKm2(s: SquareState): number {
  const e = edgeLengthM(s) / 1000;
  return e * e;
}

/** True if the whole square lies within the padded area around the loaded centre. */
export function withinPadded(
  s: SquareState,
  loaded: { lon: number; lat: number; paddedHalfM: number },
): boolean {
  const m = metresPerDegree(loaded.lat);
  const dx = Math.abs(s.lon - loaded.lon) * m.lon;
  const dy = Math.abs(s.lat - loaded.lat) * m.lat;
  return dx + s.halfWidthM <= loaded.paddedHalfM && dy + s.halfWidthM <= loaded.paddedHalfM;
}

export function utmZone(lon: number, lat: number): { zone: number; hemisphere: "N" | "S"; epsg: number } {
  const zone = Math.min(60, Math.max(1, Math.floor((lon + 180) / 6) + 1));
  const hemisphere = lat >= 0 ? "N" : "S";
  return { zone, hemisphere, epsg: (lat >= 0 ? 32600 : 32700) + zone };
}
