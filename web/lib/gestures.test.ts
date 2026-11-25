import { describe, expect, it } from "vitest";
import { GESTURE_GAP_MS, looksLikeMouseWheel, orbit, WheelGestures, wheelAction } from "./gestures";

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
  it("orbits with Option + two-finger scroll, in right-drag directions", () => {
    // fingers right (natural scrolling: negative deltaX) turn like a mouse dragged right
    expect(wheelAction(ev({ deltaX: -40, deltaY: -30, altKey: true }), true)).toEqual({ kind: "orbit", dBearing: 16, dPitch: -7.5 });
  });
  it("drops the weaker axis when one clearly dominates", () => {
    expect(orbit(-40, 5)).toEqual({ kind: "orbit", dBearing: 16, dPitch: 0 });
    expect(orbit(3, 40)).toEqual({ kind: "orbit", dBearing: 0, dPitch: 10 });
  });
});

describe("WheelGestures", () => {
  it("keeps orbiting through momentum after Option is released", () => {
    const g = new WheelGestures();
    expect(g.next(ev({ deltaX: -10, altKey: true }), 0).kind).toBe("orbit");
    expect(g.next(ev({ deltaX: -6 }), 16).kind).toBe("orbit");
    expect(g.next(ev({ deltaX: -2 }), 32).kind).toBe("orbit");
  });
  it("does not start orbiting when Option is pressed mid-pan", () => {
    const g = new WheelGestures();
    expect(g.next(ev({ deltaX: 10, wheelDeltaY: 3 }), 0).kind).toBe("pan");
    expect(g.next(ev({ deltaX: 10, altKey: true }), 16).kind).toBe("pan");
  });
  it("starts a new gesture after a pause", () => {
    const g = new WheelGestures();
    g.next(ev({ deltaX: 10 }), 0);
    expect(g.next(ev({ deltaX: 10, altKey: true }), GESTURE_GAP_MS + 1).kind).toBe("orbit");
  });
  it("always zooms on a pinch, even mid-gesture", () => {
    const g = new WheelGestures();
    g.next(ev({ deltaX: 10 }), 0);
    expect(g.next(ev({ deltaY: -5, ctrlKey: true }), 16).kind).toBe("zoom");
  });
});
