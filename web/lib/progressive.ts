import type { LayerEvent, Preview } from "./types";

/** The layers a load reports, in display order, with plain-word labels. */
export const LOAD_LAYERS: { id: string; label: string }[] = [
  { id: "streets", label: "Streets" },
  { id: "buildings", label: "Buildings" },
  { id: "landuse", label: "Land use" },
  { id: "landcover", label: "Land cover" },
  { id: "amenities", label: "Amenities" },
  { id: "terrain", label: "Terrain" },
  { id: "constraints", label: "Planning constraints" },
  { id: "building_height", label: "Building heights" },
];

const EMPTY = (): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features: [] });

/** Fold one layer event's geojson into the preview being built; later events replace the same keys. */
export function mergePreview(prev: Preview | null, geojson: Partial<Preview> | undefined): Preview | null {
  if (!geojson) return prev;
  const base: Preview = prev ?? { buildings: EMPTY(), streets: EMPTY() };
  return { ...base, ...geojson };
}

/** Labels of the load layers that have not reported yet. */
export function pendingLabels(layers: Record<string, LayerEvent>): string[] {
  return LOAD_LAYERS.filter((l) => !layers[l.id]).map((l) => l.label);
}
