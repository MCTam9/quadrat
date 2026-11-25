import { describe, expect, it } from "vitest";
import { looksLikeMouseWheel, wheelAction } from "./gestures";

const ev = (o: Partial<Parameters<typeof wheelAction>[0]>) => ({ deltaX: 0, deltaY: 0, deltaMode: 0, ctrlKey: false, ...o });

describe("wheelAction", () => {
  it("pans on a two-finger trackpad scroll", () => {
    expect(wheelAction(ev({ deltaX: 12, deltaY: -7, wheelDeltaY: 21 }), false)).toEqual({ kind: "pan", dx: 12, dy: -7 });
  });
  it("zooms on a pinch (ctrlKey) around the pointer, in towards a negative delta", () => {
    const a = wheelAction(ev({ deltaY: -10, ctrlKey: true }), true);
    expect(a.kind).toBe("zoom");
    expect(a.kind === "zoom" && a.dz).toBeCloseTo(0.1);
  });
  it("zooms on a notched mouse wheel", () => {
    const a = wheelAction(ev({ deltaY: 100, wheelDeltaY: -120 }), false);
    expect(a.kind).toBe("zoom");
    expect(a.kind === "zoom" && a.dz).toBeLessThan(0);
  });
  it("keeps panning when a fast trackpad flick looks notched", () => {
    expect(wheelAction(ev({ deltaY: 40, wheelDeltaY: -120 }), true).kind).toBe("pan");
  });
  it("treats Firefox line-mode deltas as a mouse wheel", () => {
    expect(looksLikeMouseWheel(ev({ deltaY: 3, deltaMode: 1 }))).toBe(true);
    expect(wheelAction(ev({ deltaY: 3, deltaMode: 1 }), false).kind).toBe("zoom");
  });
  it("orbits with Option + two-finger scroll", () => {
    expect(wheelAction(ev({ deltaX: 40, deltaY: -20, altKey: true }), true)).toEqual({ kind: "orbit", dBearing: 10, dPitch: 5 });
  });
});
