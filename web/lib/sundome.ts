/** The sun path as a 3D dome over the site, in local metres (east, north, up), and its projection.
 *
 *  The flat sun-path chart is a stereographic drawing of the sky. In the 3D view the same sky is
 *  a hemisphere of radius R centred on the site: each sun position is a point R metres away at
 *  its azimuth and altitude, so the dome reads directly against the extruded buildings.
 */
import { localStd, SUN_DAYS, sunPosition } from "./sunpath";

/** east, north, up in metres from the site centre. */
export type V3 = [number, number, number];

export function domePoint(azimuthDeg: number, altitudeDeg: number, R: number): V3 {
  const a = (azimuthDeg * Math.PI) / 180;
  const h = (altitudeDeg * Math.PI) / 180;
  return [R * Math.cos(h) * Math.sin(a), R * Math.cos(h) * Math.cos(a), R * Math.sin(h)];
}

export interface DomeArc {
  id: string;
  label: string;
  segments: V3[][];
  hours: { hour: number; p: V3 }[];
  /** Highest point of the day, where the label goes. */
  noon: V3 | null;
}

export interface Dome {
  arcs: DomeArc[];
  /** Analemma-style curves: one clock hour through the year. */
  hourCurves: V3[][];
  /** Altitude rings: the horizon (0) plus 30 and 60 degrees. */
  rings: { alt: number; pts: V3[] }[];
  compass: { label: string; p: V3 }[];
}

function split<T>(samples: (T | null)[]): T[][] {
  const out: T[][] = [];
  let cur: T[] = [];
  for (const s of samples) {
    if (s) cur.push(s);
    else if (cur.length) {
      out.push(cur);
      cur = [];
    }
  }
  if (cur.length) out.push(cur);
  return out;
}

export function sunDome(lat: number, lon: number, offsetH: number, R: number, year = 2023): Dome {
  const arcs: DomeArc[] = SUN_DAYS.map((d) => {
    const hours: DomeArc["hours"] = [];
    let noon: V3 | null = null;
    let best = -1;
    const samples: (V3 | null)[] = [];
    for (let m = 0; m <= 24 * 60; m += 10) {
      const s = sunPosition(localStd(year, d.month, d.day, m / 60, offsetH), lat, lon);
      if (s.altitude <= 0) {
        samples.push(null);
        continue;
      }
      const p = domePoint(s.azimuth, s.altitude, R);
      samples.push(p);
      if (m % 60 === 0) hours.push({ hour: m / 60, p });
      if (s.altitude > best) {
        best = s.altitude;
        noon = p;
      }
    }
    return { id: d.id, label: d.label, segments: split(samples), hours, noon };
  });
  const hourCurves = [6, 8, 10, 12, 14, 16, 18].flatMap((h) =>
    split(
      Array.from({ length: 62 }, (_, i) => {
        const s = sunPosition(localStd(year, 0, 1 + i * 6, h, offsetH), lat, lon);
        return s.altitude > 0 ? domePoint(s.azimuth, s.altitude, R) : null;
      }),
    ),
  );
  const rings = [0, 30, 60].map((alt) => ({ alt, pts: Array.from({ length: 73 }, (_, i) => domePoint(i * 5, alt, R)) }));
  const compass = ["N", "E", "S", "W"].map((label, i) => ({ label, p: domePoint(i * 90, 0, R * 1.1) }));
  return { arcs, hourCurves, rings, compass };
}

export interface ScreenPt {
  x: number;
  y: number;
}

/**
 * Projects local metres to CSS pixels with MapLibre's custom-layer matrix (mercator 0..1 world,
 * column-major), the same transform the map draws with, so the dome stays locked to the ground.
 * Returns null for points behind the camera.
 */
export function makeProjector(
  m: ArrayLike<number>,
  origin: { x: number; y: number; z: number },
  mercPerMetre: number,
  width: number,
  height: number,
): (v: V3) => ScreenPt | null {
  return ([e, n, u]) => {
    const x = origin.x + e * mercPerMetre;
    const y = origin.y - n * mercPerMetre; // mercator y grows southwards
    const z = origin.z + u * mercPerMetre;
    const cx = m[0] * x + m[4] * y + m[8] * z + m[12];
    const cy = m[1] * x + m[5] * y + m[9] * z + m[13];
    const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (!(cw > 1e-9)) return null;
    return { x: ((cx / cw + 1) / 2) * width, y: ((1 - cy / cw) / 2) * height };
  };
}

/** SVG path data for a projected polyline, broken where points fall behind the camera. */
export function projectedPath(pts: V3[], project: (v: V3) => ScreenPt | null): string {
  let d = "";
  let pen = false;
  for (const v of pts) {
    const s = project(v);
    if (!s) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${s.x.toFixed(1)} ${s.y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

/** "Nice" outer value for a wind-rose axis, and its ring step, so rings read as whole percentages. */
export function windAxis(maxShare: number): { axis: number; step: number } {
  const m = Math.max(0.0001, maxShare);
  const step = m > 0.2 ? 0.1 : m > 0.1 ? 0.05 : 0.02;
  return { axis: Math.ceil(m / step) * step, step };
}

export interface WindRing3D {
  rings: { share: number; pts: V3[]; outer: boolean }[];
  spokes: V3[][];
  /** One ground polygon per (direction, speed bin) with a positive share. */
  petals: { pts: V3[]; bin: number; dir: number; share: number }[];
  labels: { text: string; p: V3 }[];
}

/**
 * The wind rose as an outer ring on the ground (z = 0), in local metres: petals start at `innerM`
 * and reach `outerM` at the axis maximum. Petals point toward where the wind blows FROM.
 */
export function windRing3D(share: number[][], innerM: number, outerM: number): WindRing3D {
  const totals = share.map((r) => r.reduce((a, b) => a + b, 0));
  const { axis, step } = windAxis(Math.max(0, ...totals));
  const rad = (s: number) => innerM + (s / axis) * (outerM - innerM);
  const at = (deg: number, r: number): V3 => {
    const a = (deg * Math.PI) / 180;
    return [r * Math.sin(a), r * Math.cos(a), 0];
  };
  const circle = (r: number) => Array.from({ length: 97 }, (_, i) => at(i * 3.75, r));
  const rings: WindRing3D["rings"] = [{ share: 0, pts: circle(innerM), outer: false }];
  for (let v = step; v <= axis + 1e-9; v += step) rings.push({ share: v, pts: circle(rad(v)), outer: v + step > axis + 1e-9 });
  const spokes = [0, 45, 90, 135, 180, 225, 270, 315].map((a) => [at(a, innerM), at(a, outerM)]);
  const petals: WindRing3D["petals"] = [];
  share.forEach((bins, d) => {
    let acc = 0;
    const centre = d * 22.5;
    bins.forEach((v, b) => {
      if (v <= 0) return;
      const r0 = rad(acc);
      acc += v;
      const r1 = rad(acc);
      const arc = (r: number, from: number, to: number) => Array.from({ length: 7 }, (_, i) => at(from + ((to - from) * i) / 6, r));
      petals.push({ pts: [...arc(r0, centre - 9, centre + 9), ...arc(r1, centre + 9, centre - 9)], bin: b, dir: d, share: v });
    });
  });
  const labels = rings.filter((r) => r.share > 0).map((r) => ({ text: `${Math.round(r.share * 100)}%`, p: at(8, rad(r.share)) }));
  return { rings, spokes, petals, labels };
}
