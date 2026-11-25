import { describe, expect, it } from "vitest";
import { classifySource, knownShare, parseHeightShares, sharesFromBuildings } from "./buildings";

describe("classifySource", () => {
  it("maps vocabulary classes", () => {
    expect(classifySource("height", 12)).toBe("height");
    expect(classifySource("lidar", 18.5)).toBe("lidar");
    expect(classifySource("levels", 9)).toBe("levels");
    expect(classifySource("", null)).toBe("unknown");
    expect(classifySource("ghsl", 8)).toBe("unknown");
    expect(classifySource("height", null)).toBe("unknown");
  });
});

describe("height source shares", () => {
  it("parses the analysis fractions and rejects partial ones", () => {
    const s = parseHeightShares({ height: 0.2, lidar: 0.5, levels: 0.1, unknown: 0.2 });
    expect(s && knownShare(s)).toBeCloseTo(0.8);
    expect(parseHeightShares({ height: 1 })).toBeNull();
    expect(parseHeightShares(undefined)).toBeNull();
  });
  it("falls back to counting preview buildings", () => {
    const f = (height_source: string, height_m: number | null) =>
      ({ type: "Feature", properties: { height_source, height_m }, geometry: { type: "Point", coordinates: [0, 0] } }) satisfies GeoJSON.Feature;
    const s = sharesFromBuildings({ type: "FeatureCollection", features: [f("lidar", 10), f("levels", 6), f("", null), f("", null)] });
    expect(s && knownShare(s)).toBeCloseTo(0.5);
    expect(sharesFromBuildings(null)).toBeNull();
  });
});
