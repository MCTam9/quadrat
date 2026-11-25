export interface LonLat {
  lon: number;
  lat: number;
}

/** Parse "lat, lon" or "lon, lat"; auto-detects by range. Returns null if not a coordinate pair. */
export function parseCoordinates(input: string): LonLat | null {
  const m = input.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const a = parseFloat(m[1]);
  const b = parseFloat(m[2]);
  const aLat = Math.abs(a) <= 90;
  const bLat = Math.abs(b) <= 90;
  const aLon = Math.abs(a) <= 180;
  const bLon = Math.abs(b) <= 180;
  // Default convention is "lat, lon"; swap only when that is impossible.
  if (aLat && bLon) return { lat: a, lon: b };
  if (bLat && aLon) return { lat: b, lon: a };
  return null;
}
