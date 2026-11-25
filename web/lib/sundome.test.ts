import { describe, expect, it } from "vitest";
import { domePoint, makeProjector, projectedPath, sunDome, windAxis, windRing3D } from "./sundome";

describe("sun dome", () => {
  it("puts the zenith straight up and the horizon on the ground", () => {
    const z = domePoint(123, 90, 100);
    expect(z[2]).toBeCloseTo(100);
    expect(Math.hypot(z[0], z[1])).toBeCloseTo(0);
    const east = domePoint(90, 0, 100);
    expect(east[0]).toBeCloseTo(100);
    expect(east[2]).toBeCloseTo(0);
  });
  it("keeps every sun point on the hemisphere and above the ground", () => {
    const d = sunDome(51.5, -0.13, 0, 200);
    const pts = d.arcs.flatMap((a) => a.segments.flat());
    expect(pts.length).toBeGreaterThan(50);
    for (const p of pts) {
      expect(Math.hypot(...p)).toBeCloseTo(200, 6);
      expect(p[2]).toBeGreaterThan(0);
    }
  });
  it("has the June arc higher at noon than the December arc in London", () => {
    const d = sunDome(51.5, -0.13, 0, 200);
    const jun = d.arcs.find((a) => a.id === "jun")!.noon!;
    const dec = d.arcs.find((a) => a.id === "dec")!.noon!;
    expect(jun[2]).toBeGreaterThan(dec[2]);
    expect(dec[1]).toBeLessThan(0); // the winter sun is due south
  });
});

describe("makeProjector", () => {
  // Identity-ish matrix: clip = world, so x in [-1, 1] maps across the canvas.
  const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  it("maps world to CSS pixels and flips y", () => {
    const p = makeProjector(I, { x: 0, y: 0, z: 0 }, 0.01, 200, 100);
    expect(p([0, 0, 0])).toEqual({ x: 100, y: 50 });
    // 50 m east = 0.5 clip units = a quarter of the width to the right; north is mercator -y, clip -y, screen down
    expect(p([50, 0, 0])).toEqual({ x: 150, y: 50 });
  });
  it("drops points behind the camera and breaks the path there", () => {
    const behind = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0]; // w = z
    const p = makeProjector(behind, { x: 0, y: 0, z: 0 }, 1, 100, 100);
    expect(p([0, 0, -1])).toBeNull();
    expect(projectedPath([[0, 0, 1], [0, 0, -1], [0, 0, 2]], p)).toBe("M50.0 50.0M50.0 50.0");
  });
});

describe("windRing3D", () => {
  it("rounds the axis up to whole-percentage rings", () => {
    expect(windAxis(0.13).step).toBe(0.05);
    expect(windAxis(0.13).axis).toBeCloseTo(0.15);
    expect(windAxis(0.07).step).toBe(0.02);
  });
  it("lays petals on the ground between the inner and outer radius, pointing where the wind comes from", () => {
    const share = Array.from({ length: 16 }, (_, d) => (d === 4 ? [0.05, 0.05] : [0, 0])); // all from the east
    const w = windRing3D(share, 100, 200);
    expect(w.petals).toHaveLength(2);
    for (const p of w.petals.flatMap((x) => x.pts)) {
      expect(p[2]).toBe(0);
      expect(p[0]).toBeGreaterThan(0); // east side
      const r = Math.hypot(p[0], p[1]);
      expect(r).toBeGreaterThanOrEqual(100 - 1e-9);
      expect(r).toBeLessThanOrEqual(200 + 1e-9);
    }
  });
});
