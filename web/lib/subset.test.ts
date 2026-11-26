import { describe, expect, it } from "vitest";
import { metresPerDegree, type SquareState } from "./square";
import { subsetPreview } from "./subset";
import type { Preview } from "./types";

const LAT = 51.5;
const M = metresPerDegree(LAT);
const from: SquareState = { lon: -0.1, lat: LAT, halfWidthM: 200 };

/** A 10 m square building whose centre is (dx, dy) metres from the site centre. */
function building(dx: number, dy: number, h = 9): GeoJSON.Feature {
  const x = from.lon + dx / M.lon;
  const y = from.lat + dy / M.lat;
  const e = 5 / M.lon;
  const n = 5 / M.lat;
  return {
    type: "Feature",
    properties: { height_m: h },
    geometry: { type: "Polygon", coordinates: [[[x - e, y - n], [x + e, y - n], [x + e, y + n], [x - e, y + n], [x - e, y - n]]] },
  };
}
const line = (x0: number, y0: number, x1: number, y1: number): GeoJSON.Feature => ({
  type: "Feature",
  properties: {},
  geometry: {
    type: "LineString",
    coordinates: [
      [from.lon + x0 / M.lon, from.lat + y0 / M.lat],
      [from.lon + x1 / M.lon, from.lat + y1 / M.lat],
    ],
  },
});
const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });

const full: Preview = {
  buildings: fc([building(0, 0, 3), building(150, 0, 6), building(-150, -150, 12)]),
  context: fc([building(300, 0, 20), building(0, 340, 30)]),
  streets: fc([line(-190, 0, 190, 0), line(-190, 150, 190, 150), line(160, -190, 160, 190)]),
  landuse: fc([]),
  contours: fc([]),
  constraints: fc([]),
};

describe("subsetPreview", () => {
  const to: SquareState = { ...from, halfWidthM: 100 };

  it("keeps buildings whose centroid is inside the smaller square", () => {
    const s = subsetPreview(full, from, to)!;
    expect(s.buildings.features.map((f) => f.properties?.height_m)).toEqual([3]);
  });

  it("re-splits the ring: buildings that left the square become context, old context beyond the new ring drops", () => {
    const s = subsetPreview(full, from, to)!;
    const heights = s.context!.features.map((f) => f.properties?.height_m).sort();
    // 6 at +150 m and 12 at (-150,-150) are within 100+150 m of centre; 20 at +300 m and 30 at +340 m are not.
    expect(heights).toEqual([12, 6]);
  });

  it("promotes context buildings into the square when it moves over them", () => {
    const moved: SquareState = { lon: from.lon + 300 / M.lon, lat: LAT, halfWidthM: 50 };
    const s = subsetPreview(full, from, moved)!;
    expect(s.buildings.features.map((f) => f.properties?.height_m)).toEqual([20]);
  });

  it("keeps whole streets that touch the square and drops the rest", () => {
    const s = subsetPreview(full, from, to)!;
    expect(s.streets.features).toHaveLength(1); // only the y=0 street crosses +-100 m
  });

  it("returns the new square", () => {
    expect(subsetPreview(full, from, to)!.square?.geometry.type).toBe("Polygon");
  });

  it("returns null when the square is not inside the loaded extent", () => {
    expect(subsetPreview(full, from, { ...from, halfWidthM: 400 })).toBeNull();
    expect(subsetPreview(full, from, { ...from, lon: from.lon + 0.01 })).toBeNull();
  });

  it("accepts a nudge that stays within the old square plus ring", () => {
    expect(subsetPreview(full, from, { ...from, lon: from.lon + 100 / M.lon })).not.toBeNull();
  });
});
