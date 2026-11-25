import * as SunCalc from "suncalc";

export interface SunDay {
  label: string;
  sunrise: Date | null;
  sunset: Date | null;
  noonAltitudeDeg: number;
}

function validTime(d: Date | null | undefined): Date | null {
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

export function sunDay(label: string, date: Date, lat: number, lon: number): SunDay {
  const t = SunCalc.getTimes(date, lat, lon);
  const noon = validTime(t.solarNoon) ?? date;
  return {
    label,
    sunrise: validTime(t.sunrise),
    sunset: validTime(t.sunset),
    // suncalc 2.x returns degrees (1.x returned radians).
    noonAltitudeDeg: SunCalc.getPosition(noon, lat, lon).altitude,
  };
}

/** Today plus June and December solstices (northern-hemisphere dates; labels swap by hemisphere). */
export function sunSummary(lat: number, lon: number, now = new Date()): SunDay[] {
  const y = now.getUTCFullYear();
  const jun = new Date(Date.UTC(y, 5, 21, 12));
  const dec = new Date(Date.UTC(y, 11, 21, 12));
  return [
    sunDay("Today", now, lat, lon),
    sunDay("Jun solstice", jun, lat, lon),
    sunDay("Dec solstice", dec, lat, lon),
  ];
}
