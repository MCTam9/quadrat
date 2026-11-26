import { describe, expect, it } from "vitest";
import { duration } from "./format";

describe("duration", () => {
  it("shows milliseconds under a second and seconds above", () => {
    expect(duration(840)).toBe("840 ms");
    expect(duration(2400)).toBe("2.4 s");
    expect(duration(1000)).toBe("1.0 s");
  });
  it("is empty when unknown", () => {
    expect(duration(undefined)).toBe("");
    expect(duration(NaN)).toBe("");
    expect(duration(-5)).toBe("");
  });
});
