import { describe, expect, it } from "vitest";
import { sunRadiusM, windRingM } from "./overlay";

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
