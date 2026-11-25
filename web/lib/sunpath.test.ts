import { describe, expect, it } from "vitest";
import { projectSky, sunArc, SUN_DAYS } from "./sunpath";
import { annotateBuildings, classifyBuilding, heightBin, parseLayers, DEFAULT_LAYERS, annotateContours } from "./layers";

describe("projectSky", () => {
  it("zenith at centre, horizon at R, compass orientation", () => {
    const z = projectSky(123, 90, 100);
    expect(Math.hypot(z.x, z.y)).toBeCloseTo(0);
    const n = projectSky(0, 0, 100);
    expect(n.x).toBeCloseTo(0);
    expect(n.y).toBeCloseTo(-100); // north is up
    const e = projectSky(90, 0, 100);
    expect(e.x).toBeCloseTo(100);
    expect(e.y).toBeCloseTo(0, 5);
    // 45 deg altitude lies at tan(22.5deg) of R
    expect(Math.hypot(projectSky(180, 45, 100).x, projectSky(180, 45, 100).y)).toBeCloseTo(100 * Math.tan(Math.PI / 8));
  });
});

describe("sunArc", () => {
  it("London summer arc is higher (nearer centre) and longer than winter", () => {
    const [jun, , dec] = SUN_DAYS.map((d) => sunArc(d, 51.5, -0.1, 0, 100));
    const minR = (a: typeof jun) => Math.min(...a.segments.flat().map((p) => Math.hypot(p.x, p.y)));
    expect(minR(jun)).toBeLessThan(minR(dec));
    expect(jun.hours.length).toBeGreaterThan(dec.hours.length);
    // solar noon (12h std, lon ~0) is due south: x ~ 0, y > 0
    const noon = jun.hours.find((h) => h.hour === 12)!;
    expect(Math.abs(noon.pt.x)).toBeLessThan(5);
    expect(noon.pt.y).toBeGreaterThan(0);
  });
});

describe("building type", () => {
  it("groups OSM tags", () => {
    expect(classifyBuilding("house")).toBe("residential");
    expect(classifyBuilding("Apartments")).toBe("residential");
    expect(classifyBuilding("office")).toBe("commercial");
    expect(classifyBuilding("retail")).toBe("retail");
    expect(classifyBuilding("warehouse")).toBe("industrial");
    expect(classifyBuilding("church")).toBe("civic");
    expect(classifyBuilding("garage")).toBe("other");
    expect(classifyBuilding("yes")).toBe("unspecified");
    expect(classifyBuilding(null)).toBe("unspecified");
  });
  it("annotates features, tolerating old API shapes", () => {
    const fc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: { height_m: 9, height_source: "levels", building: "house" } }],
    };
    const p = annotateBuildings(fc).features[0].properties!;
    expect(p).toMatchObject({ btype: "residential", hcat: "storeys", h: 9 });
    expect(annotateBuildings({ type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: null }] }).features[0].properties).toMatchObject({ btype: "unspecified", h: 0 });
  });
  it("heightBin", () => {
    expect(heightBin(null)).toBe(-1);
    expect(heightBin(2)).toBe(0);
    expect(heightBin(3)).toBe(1);
    expect(heightBin(100)).toBe(6);
  });
});

describe("layer persistence + contours", () => {
  it("parses defensively", () => {
    expect(parseLayers("{bad")).toEqual(DEFAULT_LAYERS);
    expect(parseLayers(JSON.stringify({ mode: "type", overlays: { sun: true, nope: true } }))).toMatchObject({ mode: "type", overlays: { sun: true, wind: false } });
    expect(parseLayers(JSON.stringify({ mode: "zzz" })).mode).toBe("source");
  });
  it("flags major contours every 5th interval", () => {
    const fc: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [10, 12, 20].map((e) => ({ type: "Feature" as const, geometry: { type: "LineString" as const, coordinates: [[0, 0], [1, 1]] }, properties: { elevation_m: e } })) };
    const m = annotateContours(fc, 2).features.map((f) => f.properties!.major);
    expect(m).toEqual([1, 0, 1]);
  });
});

describe("building type from API use", () => {
  it("prefers the inferred use and reports evidence shares", async () => {
    const { annotateBuildings, typeSourceShares } = await import("./layers");
    const f = (props: Record<string, unknown>) => ({ type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [0, 0] }, properties: props });
    const fc = annotateBuildings({
      type: "FeatureCollection",
      features: [
        f({ building: "yes", use: "retail", use_source: "poi" }),
        f({ building: "apartments", use: "residential", use_source: "tag" }),
        f({ building: "yes", use: null, use_source: null }),
        f({ building: "office" }), // older API: no use fields
      ],
    });
    expect(fc.features.map((x) => x.properties!.btype)).toEqual(["retail", "residential", "unspecified", "commercial"]);
    expect(typeSourceShares(fc)).toEqual([
      { id: "tag", share: 0.5 },
      { id: "poi", share: 0.25 },
      { id: "none", share: 0.25 },
    ]);
  });
});
