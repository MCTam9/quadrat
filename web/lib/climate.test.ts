import { describe, expect, it } from "vitest";
import { comfortCounts, dayLabel, MONTH_START_HOUR, monthOfHour, tempColour, windRose, typicalYearLabel } from "./climate";

// Fixture: 8760 hours, constant 10 m/s... overridden per test.
const fill = <T,>(v: T) => new Array<T>(8760).fill(v);

describe("windRose", () => {
  it("bins direction (FROM) and speed", () => {
    const s = fill<number | null>(1);
    const d = fill<number | null>(0);
    s[0] = 3; d[0] = 359; // N sector, bin 4-6? no: bin 2-4 (index 1)
    s[1] = 12; d[1] = 90; // E sector, bin 10+ (index 5)
    const r = windRose(s, d);
    expect(r.total).toBe(8760);
    expect(r.share[0][1]).toBeCloseTo(1 / 8760);
    expect(r.share[4][5]).toBeCloseTo(1 / 8760);
    expect(r.prevailing).toBe(0);
    const sum = r.share.flat().reduce((a, b) => a + b, 0);
    expect(sum).toBeCloseTo(1);
  });
  it("filters by month and skips nulls", () => {
    const s = fill<number | null>(5);
    const d = fill<number | null>(180);
    s[MONTH_START_HOUR[1]] = null;
    const r = windRose(s, d, 1);
    expect(r.total).toBe(28 * 24 - 1);
    expect(r.prevailing).toBe(8);
    expect(r.meanSpeed).toBeCloseTo(5);
  });
});

describe("calendar helpers", () => {
  it("monthOfHour and dayLabel", () => {
    expect(monthOfHour(0)).toBe(0);
    expect(monthOfHour(31 * 24)).toBe(1);
    expect(monthOfHour(8759)).toBe(11);
    expect(dayLabel(0)).toBe("1 Jan");
    expect(dayLabel(31)).toBe("1 Feb");
    expect(dayLabel(364)).toBe("31 Dec");
  });
  it("typicalYearLabel", () => {
    expect(typicalYearLabel([2019, 2021])).toBe("Jan 2019, Feb 2021");
  });
});

describe("tempColour", () => {
  it("is neutral near 15 C, blue cold, red hot", () => {
    expect(tempColour(15)).toBe("rgb(233,237,241)");
    const [cr, , cb] = tempColour(-10).match(/\d+/g)!.map(Number);
    expect(cb).toBeGreaterThan(cr);
    const [hr, , hb] = tempColour(40).match(/\d+/g)!.map(Number);
    expect(hr).toBeGreaterThan(hb);
    expect(tempColour(-99)).toBe(tempColour(-10));
    expect(tempColour(null)).toBe("#9ca3af");
  });
});

describe("comfortCounts", () => {
  it("splits hours into cold / comfortable / hot per month", () => {
    const t = fill<number | null>(20);
    for (let h = 0; h < 100; h++) t[h] = 5;
    t[100] = 30;
    t[101] = 18; // boundary inclusive
    t[102] = 26;
    t[103] = null;
    const c = comfortCounts(t);
    expect(c[0]).toEqual({ cold: 100, comfortable: 31 * 24 - 100 - 2, hot: 1, unknown: 1 });
    expect(c[1].comfortable).toBe(28 * 24);
    expect(c.reduce((a, m) => a + m.cold + m.comfortable + m.hot + m.unknown, 0)).toBe(8760);
  });
});
