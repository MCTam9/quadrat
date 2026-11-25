import { describe, expect, it } from "vitest";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { buildingColour, MODES } from "./layers";

// MapLibre silently ignores an invalid paint expression and keeps the old one,
// which shows up as "selecting a colour mode does nothing".
describe("building colour expressions", () => {
  for (const m of MODES) {
    it(`${m.id} is a valid fill-color expression`, () => {
      const res = spec.expression.createExpression(buildingColour(m.id), spec.latest.paint_fill["fill-color"] as never);
      expect(res.result, JSON.stringify(res.value)).toBe("success");
    });
  }
});

describe("missing-data hatch filters", () => {
  it("is a valid filter for every mode and selects the right buildings", async () => {
    const { missingFilter } = await import("./layers");
    const f = (props: Record<string, unknown>) => ({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: [0, 0] } });
    const cases: [string, Record<string, unknown>, boolean][] = [
      ["source", { hcat: "unknown" }, true],
      ["source", { hcat: "measured" }, false],
      ["height", { h: 0 }, true],
      ["height", { h: 12 }, false],
      ["type", { btype: "unspecified" }, true],
      ["type", { btype: "retail" }, false],
      ["none", { hcat: "unknown", h: 0, btype: "unspecified" }, false],
    ];
    for (const [mode, props, expected] of cases) {
      const e = spec.expression.createExpression(missingFilter(mode as never), { type: "boolean" } as never);
      expect(e.result).toBe("success");
      const got = (e.value as { evaluate: (g: unknown, f: unknown) => boolean }).evaluate({ zoom: 15 }, f(props));
      expect(got, `${mode} ${JSON.stringify(props)}`).toBe(expected);
    }
  });

  it("No colour paints every building one neutral tone", async () => {
    const { buildingColour, NEUTRAL_BUILDING } = await import("./layers");
    expect(buildingColour("none")).toBe(NEUTRAL_BUILDING);
  });
});
