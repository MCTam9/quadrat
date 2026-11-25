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

type Pt = { x: number; y: number };
type M3 = [number, number, number, number, number, number, number, number, number];

function adj(m: M3): M3 {
  const [a, b, c, d, e, f, g, h, i] = m;
  return [e * i - f * h, c * h - b * i, b * f - c * e, f * g - d * i, a * i - c * g, c * d - a * f, d * h - e * g, b * g - a * h, a * e - b * d];
}
function mul(m: M3, n: M3): M3 {
  const r = new Array(9).fill(0) as M3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) r[3 * i + j] += m[3 * i + k] * n[3 * k + j];
  return r;
}
/** The projective map sending the unit-square basis (0,0),(1,0),(0,1),(1,1)-style frame to four points. */
function basisTo(p: [Pt, Pt, Pt, Pt]): M3 {
  const m: M3 = [p[0].x, p[1].x, p[2].x, p[0].y, p[1].y, p[2].y, 1, 1, 1];
  const v = adj(m);
  const s = [v[0] * p[3].x + v[1] * p[3].y + v[2], v[3] * p[3].x + v[4] * p[3].y + v[5], v[6] * p[3].x + v[7] * p[3].y + v[8]];
  return mul(m, [s[0], 0, 0, 0, s[1], 0, 0, 0, s[2]]);
}

/** Whether four points, in order, form a convex quad (false when part of it is past the horizon). */
export function isConvexQuad(q: [Pt, Pt, Pt, Pt]): boolean {
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const a = q[i], b = q[(i + 1) % 4], c = q[(i + 2) % 4];
    const z = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    if (!Number.isFinite(z) || Math.abs(z) < 1e-9) return false;
    if (sign === 0) sign = Math.sign(z);
    else if (Math.sign(z) !== sign) return false;
  }
  return true;
}

/**
 * CSS `matrix3d` taking a `size`×`size` box (transform-origin 0 0) onto the screen quad `dst`,
 * corners in order top-left, top-right, bottom-right, bottom-left. This lays a flat drawing on
 * the map's ground plane under any pitch and bearing.
 */
export function quadTransform(size: number, dst: [Pt, Pt, Pt, Pt]): string {
  const src: [Pt, Pt, Pt, Pt] = [{ x: 0, y: 0 }, { x: size, y: 0 }, { x: 0, y: size }, { x: size, y: size }];
  const d: [Pt, Pt, Pt, Pt] = [dst[0], dst[1], dst[3], dst[2]];
  const h = mul(basisTo(d), adj(basisTo(src)));
  const n = h.map((v) => v / h[8]);
  // 3x3 [a b c; d e f; g h i] -> column-major 4x4 for CSS
  return `matrix3d(${[n[0], n[3], 0, n[6], n[1], n[4], 0, n[7], 0, 0, 1, 0, n[2], n[5], 0, n[8]].join(",")})`;
}
