import { describe, expect, it } from "vitest";
import { resolveDark } from "./theme";
import { THEME_BOOT } from "./theme-boot";

describe("theme", () => {
  it("follows the OS only on Auto", () => {
    expect(resolveDark("system", true)).toBe(true);
    expect(resolveDark("system", false)).toBe(false);
    expect(resolveDark("light", true)).toBe(false);
    expect(resolveDark("dark", false)).toBe(true);
  });
  it("boot script is valid JavaScript", () => {
    expect(() => new Function(THEME_BOOT)).not.toThrow();
  });
});
