import { describe, expect, it } from "vitest";
import { isConvexQuad, quadTransform, sunRadiusM, windRingM } from "./overlay";

describe("overlay geometry", () => {
  it("starts wind petals beyond the circumscribed radius of the square", () => {
    for (const half of [50, 300, 1000]) {
      const { innerM, outerM } = windRingM(half);
      expect(innerM).toBeGreaterThan(half * Math.SQRT2);
      expect(outerM).toBeGreaterThan(innerM);
    }
  });
  it("keeps the sun path inside the square", () => {
    expect(sunRadiusM(300)).toBeLessThan(300);
    expect(sunRadiusM(300)).toBeLessThan(windRingM(300).innerM);
  });
});

/** Apply a CSS matrix3d string to a 2D point (z = 0), with the perspective divide. */
function apply(css: string, x: number, y: number) {
  const m = css.slice(9, -1).split(",").map(Number);
  const w = m[3] * x + m[7] * y + m[15];
  return { x: (m[0] * x + m[4] * y + m[12]) / w, y: (m[1] * x + m[5] * y + m[13]) / w };
}

describe("quadTransform", () => {
  it("sends the box corners onto a perspective quad", () => {
    const dst = [{ x: 120, y: 80 }, { x: 380, y: 90 }, { x: 460, y: 300 }, { x: 40, y: 280 }] as const;
    const t = quadTransform(200, [...dst] as never);
    const got = [apply(t, 0, 0), apply(t, 200, 0), apply(t, 200, 200), apply(t, 0, 200)];
    got.forEach((p, i) => {
      expect(p.x).toBeCloseTo(dst[i].x, 6);
      expect(p.y).toBeCloseTo(dst[i].y, 6);
    });
  });
  it("is a pure translation for an unrotated, unpitched box", () => {
    const t = quadTransform(100, [{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 110, y: 120 }, { x: 10, y: 120 }]);
    expect(apply(t, 50, 50)).toEqual({ x: 60, y: 70 });
  });
  it("rejects a quad folded past the horizon", () => {
    expect(isConvexQuad([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }])).toBe(false);
    expect(isConvexQuad([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }])).toBe(true);
  });
});
