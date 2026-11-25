import { describe, expect, it } from "vitest";
import { formatCoords, nameCacheKey, siteNameFrom } from "./site-name";

describe("siteNameFrom", () => {
  it("prefers name, then street, then district", () => {
    expect(siteNameFrom({ name: "Trafalgar Square", street: "The Strand", city: "London" })).toEqual({ title: "Trafalgar Square", place: "London" });
    expect(siteNameFrom({ street: "Whitehall", district: "Westminster", city: "London" })?.title).toBe("Whitehall");
    expect(siteNameFrom({ district: "Westminster" })).toEqual({ title: "Westminster", place: null });
  });
  it("drops a city that repeats the title and returns null when nothing names the site", () => {
    expect(siteNameFrom({ name: "London", city: "London" })?.place).toBeNull();
    expect(siteNameFrom({ name: "  " })).toBeNull();
    expect(siteNameFrom(undefined)).toBeNull();
  });
});

describe("coordinates", () => {
  it("formats with hemispheres", () => {
    expect(formatCoords(51.5072, -0.1276)).toBe("51.50720° N, 0.12760° W");
    expect(formatCoords(-33.8688, 151.2093)).toBe("33.86880° S, 151.20930° E");
  });
  it("caches nearby points together", () => {
    expect(nameCacheKey(-0.12761, 51.50721)).toBe(nameCacheKey(-0.12764, 51.50719));
    expect(nameCacheKey(-0.1276, 51.5072)).not.toBe(nameCacheKey(-0.1296, 51.5072));
  });
});
