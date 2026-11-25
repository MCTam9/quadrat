export type HeightCategory = "measured" | "storeys" | "estimated" | "unknown";

export const HEIGHT_CATEGORIES: { id: HeightCategory; label: string; color: string }[] = [
  { id: "measured", label: "Measured (tag or LiDAR)", color: "#2563eb" },
  { id: "storeys", label: "From storeys (levels × 3 m)", color: "#0d9488" },
  { id: "estimated", label: "Estimated", color: "#f59e0b" },
  { id: "unknown", label: "Unknown (flat)", color: "#9ca3af" },
];

/**
 * Backend height_source values: "height" (explicit tag), "lidar" (EA LiDAR nDSM, England),
 * "levels" (levels * 3 m), "" (unknown).
 * Anything else non-empty (e.g. a raster/model fallback) is treated as an estimate.
 */
export function classifySource(source: unknown, heightM: unknown): HeightCategory {
  const s = typeof source === "string" ? source.trim().toLowerCase() : "";
  const hasHeight = typeof heightM === "number" && Number.isFinite(heightM) && heightM > 0;
  if (!s) return "unknown";
  if (s === "height" || s === "lidar" || s === "measured") return hasHeight ? "measured" : "unknown";
  if (s === "levels" || s === "storeys") return hasHeight ? "storeys" : "unknown";
  return hasHeight ? "estimated" : "unknown";
}
