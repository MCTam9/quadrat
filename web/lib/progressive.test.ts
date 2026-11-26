import { describe, expect, it } from "vitest";
import type { LayerEvent } from "./types";
import { acceptEvent, doneCount, fromTiles, LOAD_LAYERS, mergePreview, pendingLabels, rowState } from "./progressive";

const fc = (n: number): GeoJSON.FeatureCollection => ({
  type: "FeatureCollection",
  features: Array.from({ length: n }, () => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [0, 0] } })),
});

describe("progressive load", () => {
  it("merges layer geojson per key, later events replacing earlier ones", () => {
    let p = mergePreview(null, { streets: fc(2) });
    expect(p?.streets.features).toHaveLength(2);
    expect(p?.buildings.features).toHaveLength(0);
    p = mergePreview(p, { buildings: fc(1), context: fc(3) });
    p = mergePreview(p, { buildings: fc(5) });
    expect(p?.buildings.features).toHaveLength(5);
    expect(p?.context?.features).toHaveLength(3);
    expect(p?.streets.features).toHaveLength(2);
  });

  it("leaves the preview alone for events without geojson", () => {
    expect(mergePreview(null, undefined)).toBeNull();
  });

  it("lists the layers still pending, in display order", () => {
    expect(LOAD_LAYERS).toHaveLength(8);
    expect(pendingLabels({ streets: { layer: "streets", ok: true } })[0]).toBe("Buildings");
    expect(pendingLabels({})).toHaveLength(8);
  });

  it("treats a draft as pending for the checklist count and the status pill", () => {
    const draft: LayerEvent = { layer: "buildings", ok: true, draft: true, provider: "tiles_buildings" };
    const layers = { streets: { layer: "streets", ok: true }, buildings: draft };
    expect(rowState(draft)).toBe("draft");
    expect(rowState(undefined)).toBe("pending");
    expect(rowState({ layer: "x", ok: false })).toBe("failed");
    expect(doneCount(layers)).toBe(1);
    expect(pendingLabels(layers)).toContain("Buildings");
    expect(pendingLabels({ ...layers, buildings: { layer: "buildings", ok: true } })).not.toContain("Buildings");
  });

  it("marks a finished layer as from map tiles only when its final provider is a tiles_* one", () => {
    expect(fromTiles({ layer: "streets", ok: true, provider: "tiles_streets" })).toBe(true);
    expect(fromTiles({ layer: "streets", ok: true, provider: "osm_streets" })).toBe(false);
    expect(fromTiles({ layer: "streets", ok: true, draft: true, provider: "tiles_streets" })).toBe(false);
    expect(fromTiles({ layer: "streets", ok: false, provider: "tiles_streets" })).toBe(false);
    expect(fromTiles(undefined)).toBe(false);
  });

  it("applies a draft first, the real event after it, and ignores a draft that arrives late", () => {
    const real = new Set<string>();
    expect(acceptEvent(real, { layer: "buildings", ok: true, draft: true })).toBe(true);
    expect(acceptEvent(real, { layer: "buildings", ok: true, provider: "osm_buildings" })).toBe(true);
    expect(acceptEvent(real, { layer: "buildings", ok: true, draft: true })).toBe(false);
    // the follow-up buildings update does not count as the real layer, but a draft is stale by then anyway
    expect(acceptEvent(real, { layer: "buildings", ok: true, update: true })).toBe(true);
    // other layers are unaffected
    expect(acceptEvent(real, { layer: "streets", ok: true, draft: true })).toBe(true);
  });
});
