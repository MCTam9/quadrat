import { describe, expect, it } from "vitest";
import { blueprintColour } from "./blueprint";

describe("blueprintColour", () => {
  it("keeps water darker than land and roads darker than the sheet", () => {
    expect(blueprintColour("water", "fill", 0.01)).toBe("#0e0e0e");
    expect(blueprintColour("landuse_park", "fill", 0.2)).toBe("#1f1f1f");
    expect(blueprintColour("highway_minor", "line", 0.02)).toBe("#0a0a0a");
    expect(blueprintColour("highway_major_casing", "line", 0.25)).toBe("#474747");
  });
  it("sets text halos to the sheet colour", () => {
    expect(blueprintColour("place_city", "halo", 0)).toBe("#161616");
  });
});
