import { describe, expect, it } from "vitest";
import { LOAD_LAYERS, mergePreview, pendingLabels } from "./progressive";

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
});
