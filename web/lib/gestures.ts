/** Trackpad-friendly wheel handling for the map.
 *
 *  MapLibre turns every wheel event into zoom, so a MacBook two-finger scroll zooms
 *  instead of panning. Here, as in Figma or Google Maps:
 *  - pinch (the browser reports it as a wheel event with ctrlKey) zooms around the pointer;
 *  - two-finger scroll pans;
 *  - a notched mouse wheel still zooms;
 *  - Option (Alt) + two-finger scroll orbits: sideways turns the map, up and down tilts it.
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
  if (e.altKey) return { kind: "orbit", dBearing: dx * 0.25, dPitch: -dy * 0.25 };
  if (e.ctrlKey || e.metaKey) return { kind: "zoom", dz: -dy / 100 }; // pinch, or cmd/ctrl + scroll
  if (!trackpadRecent && looksLikeMouseWheel(e)) return { kind: "zoom", dz: -dy / 450 };
  return { kind: "pan", dx, dy };
}
