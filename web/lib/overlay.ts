/** Geometry of the sky overlays, in metres from the square's centre. */

/** The sun path sits inside the square; its compass letters land just inside the edge. */
export function sunRadiusM(halfWidthM: number): number {
  return halfWidthM * 0.86;
}

/**
 * The wind rose is an outer ring: petals start beyond the square's circumscribed circle
 * (centre to corner), so they never cover the sun path or the red line.
 */
export function windRingM(halfWidthM: number): { innerM: number; outerM: number } {
  const innerM = halfWidthM * Math.SQRT2 * 1.05;
  return { innerM, outerM: innerM + halfWidthM * 0.7 };
}
