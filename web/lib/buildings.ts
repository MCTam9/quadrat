import { HEIGHT_SOURCE, type HeightSourceId } from "./vocab.generated";

export type HeightCategory = HeightSourceId;
export const HEIGHT_CATEGORIES = HEIGHT_SOURCE;

const IDS = new Set<string>(HEIGHT_SOURCE.map((h) => h.id));

/**
 * Backend `height_source` is one of the vocabulary classes: height (tag), lidar (nDSM),
 * levels (storeys x 3 m) or unknown. Anything else, or a source without a usable height, is unknown.
 */
export function classifySource(source: unknown, heightM: unknown): HeightCategory {
  const s = typeof source === "string" ? source.trim().toLowerCase() : "";
  const hasHeight = typeof heightM === "number" && Number.isFinite(heightM) && heightM > 0;
  if (!hasHeight || !IDS.has(s)) return "unknown";
  return s as HeightCategory;
}

export type HeightShares = Record<HeightCategory, number>;

/** `metrics.fabric.height_source_shares` from the analysis; null unless it is a usable set of fractions. */
export function parseHeightShares(v: unknown): HeightShares | null {
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const out = { height: 0, lidar: 0, levels: 0, unknown: 0 } as HeightShares;
  for (const id of Object.keys(out) as HeightCategory[]) {
    const n = o[id];
    if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return null;
    out[id] = n;
  }
  return out;
}

/** Fallback when the analysis predates height_source_shares: count the preview buildings. */
export function sharesFromBuildings(fc: GeoJSON.FeatureCollection | null): HeightShares | null {
  const feats = fc?.features ?? [];
  if (!feats.length) return null;
  const out = { height: 0, lidar: 0, levels: 0, unknown: 0 } as HeightShares;
  for (const f of feats) out[classifySource(f.properties?.height_source, f.properties?.height_m)] += 1;
  for (const id of Object.keys(out) as HeightCategory[]) out[id] /= feats.length;
  return out;
}

/** Share of buildings with a known height (tag, LiDAR or storeys). */
export function knownShare(s: HeightShares): number {
  return Math.max(0, Math.min(1, 1 - s.unknown));
}
