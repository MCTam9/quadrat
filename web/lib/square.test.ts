import { describe, expect, it } from "vitest";
import {
  areaKm2, clampHalf, metresPerDegree, moveCentre, resizeFromCorner, setEdgeLength,
  squareCorners, squareRing, utmZone, withinPadded, zoomToFit,
} from "./square";
import { parseCoordinates } from "./coords";

const s = { lon: 10, lat: 60, halfWidthM: 250 };

describe("square", () => {
  it("builds a closed ring about the centre with metre-accurate sides", () => {
    const ring = squareRing(s);
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);
    const m = metresPerDegree(s.lat);
    const w = (ring[1][0] - ring[0][0]) * m.lon;
    const h = (ring[0][1] - ring[3][1]) * m.lat;
    expect(w).toBeCloseTo(500, 6);
    expect(h).toBeCloseTo(500, 6);
  });
  it("resizes symmetrically from a corner and stays square", () => {
    const c = squareCorners(s)[1];
    const r = resizeFromCorner(s, [c[0] + 0.001, c[1]]);
    expect(r.lon).toBe(s.lon);
    expect(r.lat).toBe(s.lat);
    expect(r.halfWidthM).toBeGreaterThan(250);
  });
  it("clamps size", () => {
    expect(clampHalf(5)).toBe(50);
    expect(clampHalf(99999)).toBe(1000);
    expect(setEdgeLength(s, 2000).halfWidthM).toBe(1000);
    expect(setEdgeLength(s, 10).halfWidthM).toBe(50);
  });
  it("computes area", () => {
    expect(areaKm2(s)).toBeCloseTo(0.25, 10);
  });
  it("moves the centre", () => {
    expect(moveCentre(s, 11, 61)).toMatchObject({ lon: 11, lat: 61, halfWidthM: 250 });
  });
  it("checks padded containment", () => {
    const loaded = { lon: 10, lat: 60, paddedHalfM: 600 };
    expect(withinPadded(s, loaded)).toBe(true);
    expect(withinPadded({ ...s, lon: 10.02 }, loaded)).toBe(false);
  });
  it("finds UTM zone", () => {
    expect(utmZone(10, 60)).toEqual({ zone: 32, hemisphere: "N", epsg: 32632 });
    expect(utmZone(-70, -33).epsg).toBe(32719);
  });
});

describe("parseCoordinates", () => {
  it("accepts lat, lon", () => expect(parseCoordinates("51.5, -0.12")).toEqual({ lat: 51.5, lon: -0.12 }));
  it("auto-detects lon, lat", () => expect(parseCoordinates("151.2, -33.9")).toEqual({ lat: -33.9, lon: 151.2 }));
  it("rejects text and out of range", () => {
    expect(parseCoordinates("London")).toBeNull();
    expect(parseCoordinates("200, 300")).toBeNull();
  });
});

describe("zoomToFit", () => {
  it("zooms out for bigger squares and smaller screens", () => {
    expect(zoomToFit(500, 51.5, 800)).toBeLessThan(zoomToFit(125, 51.5, 800));
    expect(zoomToFit(300, 51.5, 390)).toBeLessThan(zoomToFit(300, 51.5, 900));
  });
  it("puts a 600 m square across about 60 % of a 900 px screen", () => {
    const z = zoomToFit(300, 51.5, 900);
    const mPerPx = (78_271.517 * Math.cos((51.5 * Math.PI) / 180)) / 2 ** z;
    expect(600 / mPerPx / 900).toBeCloseTo(0.6, 1);
  });
});
