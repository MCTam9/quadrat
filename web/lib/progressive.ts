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

/**
 * Whether a layer event should be applied. `real` is the set of layers whose real (non-draft)
 * event has arrived in this load; it is updated here. A draft arriving after the real layer is
 * stale (the server already refuses these, this is the second guard against a reordered stream).
 */
export function acceptEvent(real: Set<string>, ev: LayerEvent): boolean {
  if (ev.draft) return !real.has(ev.layer);
  if (!ev.update) real.add(ev.layer);
  return true;
}

/** Where a checklist row is: waiting, drawn from map tiles, finished, or failed. */
export type RowState = "pending" | "draft" | "done" | "failed";

export function rowState(l: LayerEvent | undefined): RowState {
  if (!l) return "pending";
  if (l.draft) return "draft";
  return l.ok ? "done" : "failed";
}

/** True when a finished layer's data came from map tiles (Overpass was slow or failed): approximate. */
export function fromTiles(l: LayerEvent | undefined): boolean {
  return !!l && !l.draft && l.ok && (l.provider ?? "").startsWith("tiles_");
}

/** Layers that have a final result (a draft does not count). */
export function doneCount(layers: Record<string, LayerEvent>): number {
  return LOAD_LAYERS.filter((l) => {
    const s = rowState(layers[l.id]);
    return s === "done" || s === "failed";
  }).length;
}

/** Labels of the load layers still waiting for their final result (drafts included). */
export function pendingLabels(layers: Record<string, LayerEvent>): string[] {
  return LOAD_LAYERS.filter((l) => {
    const s = rowState(layers[l.id]);
    return s === "pending" || s === "draft";
  }).map((l) => l.label);
}
