/** Trackpad-friendly wheel handling for the map.
 *
 *  MapLibre turns every wheel event into zoom, so a MacBook two-finger scroll zooms
 *  instead of panning. Here, as in Figma or Google Maps:
 *  - pinch (the browser reports it as a wheel event with ctrlKey) zooms around the pointer;
 *  - two-finger scroll pans;
 *  - a notched mouse wheel still zooms;
 *  - Option (Alt) + two-finger scroll orbits like a turntable around the site, in the same
 *    directions as a right-button drag: fingers right turn the site as if dragging it right,
 *    fingers up tilt towards the horizon.
 *
 *  A two-finger gesture keeps one meaning from first touch until it (and its momentum) ends, so
 *  pressing or releasing Option mid-gesture, or momentum after lifting, never flips a pan into an
 *  orbit or back. That flipping is what made orbiting feel jumpy.
 */

export type WheelAction =
  | { kind: "pan"; dx: number; dy: number }
  | { kind: "zoom"; dz: number }
  | { kind: "orbit"; dBearing: number; dPitch: number };

export interface WheelLike {
  deltaX: number;
  deltaY: number;
  deltaMode: number;
  ctrlKey: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  /** Legacy, non-standard: multiples of 120 for a notched mouse wheel (Chrome, Safari). */
  wheelDeltaY?: number;
}

/** Time a trackpad stays "recent" so a fast flick that happens to look notched still pans. */
export const TRACKPAD_MEMORY_MS = 500;

const LINE_PX = 16;

/** Whether one event looks like a notched mouse wheel rather than a trackpad. */
export function looksLikeMouseWheel(e: WheelLike): boolean {
  if (e.deltaMode === 1) return true; // Firefox reports mouse wheels in lines
  if (e.deltaX !== 0) return false; // mouse wheels do not scroll sideways
  const w = e.wheelDeltaY;
  return w !== undefined && w !== 0 && Math.abs(w) % 120 === 0;
}

/** What one wheel event should do. `pageHeight` converts page-mode deltas to pixels. */
export function wheelAction(e: WheelLike, trackpadRecent: boolean, pageHeight = 800): WheelAction {
  const unit = e.deltaMode === 1 ? LINE_PX : e.deltaMode === 2 ? pageHeight : 1;
  const dx = e.deltaX * unit;
  const dy = e.deltaY * unit;
  if (e.altKey) return orbit(dx, dy);
  if (e.ctrlKey || e.metaKey) return { kind: "zoom", dz: -dy / 100 }; // pinch, or cmd/ctrl + scroll
  if (!trackpadRecent && looksLikeMouseWheel(e)) return { kind: "zoom", dz: -dy / 450 };
  return { kind: "pan", dx, dy };
}

/** Degrees per trackpad pixel: gentler than MapLibre's mouse drag (0.8 and 0.5), as fingers move less. */
export const ORBIT_TURN = 0.4;
export const ORBIT_TILT = 0.25;

/**
 * Orbit from a scroll delta. With natural scrolling, fingers moving right give a negative deltaX,
 * the same as a mouse moving right; so this matches MapLibre's right-drag. The weaker axis is
 * dropped when one clearly dominates, so a sideways swipe turns without wobbling the tilt.
 */
export function orbit(dx: number, dy: number): WheelAction {
  let turn = -dx * ORBIT_TURN;
  let tilt = dy * ORBIT_TILT;
  if (Math.abs(dx) > 2 * Math.abs(dy)) tilt = 0;
  else if (Math.abs(dy) > 2 * Math.abs(dx)) turn = 0;
  return { kind: "orbit", dBearing: turn, dPitch: tilt };
}

/** Gap after which the next wheel event starts a new gesture (momentum events arrive every ~16 ms). */
export const GESTURE_GAP_MS = 150;

/**
 * Wheel events grouped into gestures. The first event decides pan, orbit or zoom; the rest of the
 * gesture keeps it. Pinch (ctrlKey) is always zoom: browsers set it per event for pinches only.
 */
export class WheelGestures {
  private mode: "pan" | "orbit" | "zoom" | null = null;
  private lastAt = -Infinity;
  private trackpadAt = -Infinity;

  next(e: WheelLike, now: number, pageHeight = 800): WheelAction {
    const fresh = now - this.lastAt > GESTURE_GAP_MS;
    this.lastAt = now;
    const recentTrackpad = now - this.trackpadAt < TRACKPAD_MEMORY_MS;
    if (!e.ctrlKey && !looksLikeMouseWheel(e)) this.trackpadAt = now;
    if (e.ctrlKey || e.metaKey) return wheelAction(e, true, pageHeight);
    const act = wheelAction(e, recentTrackpad, pageHeight);
    if (fresh || this.mode === null || this.mode === "zoom") this.mode = act.kind;
    if (act.kind === this.mode) return act;
    // keep the gesture's meaning: re-read this event's deltas in the locked mode
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? pageHeight : 1;
    const dx = e.deltaX * unit;
    const dy = e.deltaY * unit;
    return this.mode === "orbit" ? orbit(dx, dy) : { kind: "pan", dx, dy };
  }
}
