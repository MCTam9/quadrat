export interface PhotonProps {
  name?: string;
  street?: string;
  district?: string;
  city?: string;
  [k: string]: unknown;
}

export interface SiteName {
  /** Place name for the title block: name, else street, else district. */
  title: string;
  /** City, when it adds something to the title. */
  place: string | null;
}

const clean = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);

/** Name a site from a Photon reverse-geocode feature; null when it names nothing. */
export function siteNameFrom(p: PhotonProps | null | undefined): SiteName | null {
  if (!p) return null;
  const title = clean(p.name) ?? clean(p.street) ?? clean(p.district);
  if (!title) return null;
  const city = clean(p.city);
  return { title, place: city && city.toLowerCase() !== title.toLowerCase() ? city : null };
}

/** "51.50720° N, 0.12760° W": the fallback title when nothing names the site. */
export function formatCoords(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(5)}° ${lon >= 0 ? "E" : "W"}`;
}

/** Cache key: 3 decimals is about 100 m, so dragging within a block reuses one lookup. */
export function nameCacheKey(lon: number, lat: number): string {
  return `${lat.toFixed(3)},${lon.toFixed(3)}`;
}

const cache = new Map<string, SiteName | null>();

export async function reverseName(lon: number, lat: number, signal?: AbortSignal): Promise<SiteName | null> {
  const key = nameCacheKey(lon, lat);
  if (cache.has(key)) return cache.get(key) ?? null;
  const res = await fetch(`https://photon.komoot.io/reverse?lon=${lon.toFixed(6)}&lat=${lat.toFixed(6)}&limit=1`, { signal });
  if (!res.ok) throw new Error(`Name lookup failed (${res.status})`);
  const j = (await res.json()) as { features?: { properties?: PhotonProps }[] };
  const name = siteNameFrom(j.features?.[0]?.properties);
  cache.set(key, name);
  return name;
}
