import * as SunCalc from "suncalc";

export interface Pt {
  x: number;
  y: number;
}

/** Stereographic projection of a sky position onto a disc of radius R: zenith at centre, horizon at R, north up, east right. */
export function projectSky(azimuthDeg: number, altitudeDeg: number, R: number): Pt {
  const r = R * Math.tan(((90 - altitudeDeg) * Math.PI) / 360);
  const a = (azimuthDeg * Math.PI) / 180;
  return { x: r * Math.sin(a), y: -r * Math.cos(a) };
}

/** UTC instant for local *standard* time (offset hours east of UTC) on a calendar day. */
export function localStd(year: number, month: number, day: number, hour: number, offsetH: number): Date {
  return new Date(Date.UTC(year, month, day, 0, 0, 0) + (hour - offsetH) * 3_600_000);
}

export function sunPosition(date: Date, lat: number, lon: number): { azimuth: number; altitude: number } {
  const p = SunCalc.getPosition(date, lat, lon); // degrees; azimuth clockwise from north
  return { azimuth: p.azimuth, altitude: p.altitude };
}

export interface SunArc {
  id: string;
  label: string;
  /** Polyline segments (above the horizon only). */
  segments: Pt[][];
  /** Whole-hour positions above the horizon. */
  hours: { hour: number; pt: Pt }[];
}

export const SUN_DAYS: { id: string; label: string; month: number; day: number }[] = [
  { id: "jun", label: "21 Jun", month: 5, day: 21 },
  { id: "equ", label: "21 Mar / Sep", month: 2, day: 20 },
  { id: "dec", label: "21 Dec", month: 11, day: 21 },
];

export function sunArc(day: (typeof SUN_DAYS)[number], lat: number, lon: number, offsetH: number, R: number, year = 2023): SunArc {
  const segments: Pt[][] = [];
  const hours: SunArc["hours"] = [];
  let cur: Pt[] = [];
  for (let m = 0; m <= 24 * 60; m += 10) {
    const p = sunPosition(localStd(year, day.month, day.day, m / 60, offsetH), lat, lon);
    if (p.altitude > 0) {
      const pt = projectSky(p.azimuth, p.altitude, R);
      cur.push(pt);
      if (m % 60 === 0) hours.push({ hour: m / 60, pt });
    } else if (cur.length) {
      segments.push(cur);
      cur = [];
    }
  }
  if (cur.length) segments.push(cur);
  return { id: day.id, label: day.label, segments, hours };
}

/** Faint analemma-style curve: the sun's position at one clock hour through the year. */
export function hourCurve(hour: number, lat: number, lon: number, offsetH: number, R: number, year = 2023): Pt[][] {
  const segs: Pt[][] = [];
  let cur: Pt[] = [];
  for (let d = 0; d <= 365; d += 6) {
    const p = sunPosition(localStd(year, 0, 1 + d, hour, offsetH), lat, lon);
    if (p.altitude > 0) cur.push(projectSky(p.azimuth, p.altitude, R));
    else if (cur.length) {
      segs.push(cur);
      cur = [];
    }
  }
  if (cur.length) segs.push(cur);
  return segs;
}

export function pathD(pts: Pt[], cx = 0, cy = 0): string {
  return pts.map((p, i) => `${i ? "L" : "M"}${(cx + p.x).toFixed(1)} ${(cy + p.y).toFixed(1)}`).join("");
}

/** Offset (h) used when the climate timezone is not known: nearest 15 degree meridian. */
export function approxOffsetH(lon: number): number {
  return Math.round(lon / 15);
}
