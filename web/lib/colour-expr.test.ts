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
      // featureFilter is what the map itself runs, legacy-syntax detection included;
      // createExpression alone accepted ["==", 1, 0], which the map rejects.
      const filter = missingFilter(mode as never);
      const got = spec.featureFilter(filter as never, "layers[0].filter").filter({ zoom: 15 } as never, f(props) as never);
      expect(got, `${mode} ${JSON.stringify(props)}`).toBe(expected);
    }
  });

  it("No colour paints every building in ink", async () => {
    const { buildingColour, NEUTRAL_BUILDING } = await import("./layers");
    expect(buildingColour("none")).toBe(NEUTRAL_BUILDING);
    expect(NEUTRAL_BUILDING).toBe("#000000");
  });
});

describe("constraint groups", () => {
  it("groups the preview constraints by dataset", async () => {
    const { constraintGroups } = await import("./layers");
    const f = (dataset: string, name: string) => ({ type: "Feature", properties: { dataset, name }, geometry: { type: "Point", coordinates: [0, 0] } });
    const g = constraintGroups({ type: "FeatureCollection", features: [f("conservation-area", "Soho"), f("conservation-area", "Soho"), f("listed-building", "No 10")] } as never);
    expect(g).toEqual([
      { dataset: "conservation-area", label: "Conservation area", count: 2, names: ["Soho"] },
      { dataset: "listed-building", label: "Listed building", count: 1, names: ["No 10"] },
    ]);
  });
});

describe("dark palette", () => {
  it("paints No colour in white on the dark sheet and every mode stays a valid expression", () => {
    expect(buildingColour("none", true)).toBe("#ffffff");
    for (const m of MODES) {
      const res = spec.expression.createExpression(buildingColour(m.id, true), spec.latest.paint_fill["fill-color"] as never);
      expect(res.result, m.id).toBe("success");
    }
  });
});
