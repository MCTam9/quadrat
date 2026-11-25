import { describe, expect, it } from "vitest";
import { classifySource } from "./buildings";

describe("classifySource", () => {
  it("maps provider values", () => {
    expect(classifySource("height", 12)).toBe("measured");
    expect(classifySource("lidar", 18.5)).toBe("measured");
    expect(classifySource("levels", 9)).toBe("storeys");
    expect(classifySource("", null)).toBe("unknown");
    expect(classifySource("ghsl", 8)).toBe("estimated");
    expect(classifySource("height", null)).toBe("unknown");
  });
});
