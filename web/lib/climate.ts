export const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
export const HOURS = 8760;

/** First hour index of each month (0-based) plus the end sentinel. */
export const MONTH_START_HOUR: number[] = DAYS_IN_MONTH.reduce<number[]>((acc, d, i) => {
  acc.push(acc[i] + d * 24);
  return acc;
}, [0]);

export function monthOfHour(h: number): number {
  let m = 0;
  while (m < 11 && h >= MONTH_START_HOUR[m + 1]) m++;
  return m;
}

/** Date label for a day-of-year index (0..364), e.g. "14 Mar". */
export function dayLabel(day: number): string {
  let d = Math.max(0, Math.min(364, Math.floor(day)));
  let m = 0;
  while (d >= DAYS_IN_MONTH[m]) d -= DAYS_IN_MONTH[m++];
  return `${d + 1} ${MONTH_NAMES[m]}`;
}

// ---- wind rose ----
export const WIND_BINS = [0, 2, 4, 6, 8, 10];
export const WIND_BIN_LABELS = ["0-2", "2-4", "4-6", "6-8", "8-10", "10+"];
/** Sequential graphite-to-ink ramp, calm to strong (CSS variables: they flip in dark mode). */
export const WIND_COLOURS = ["var(--wind-0)", "var(--wind-1)", "var(--wind-2)", "var(--wind-3)", "var(--wind-4)", "var(--wind-5)"];
export const COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

export interface WindRose {
  /** share[d][b] = fraction of valid hours (0..1) with wind FROM sector d and speed bin b. */
  share: number[][];
  total: number;
  prevailing: number | null;
  meanSpeed: number | null;
}

export function speedBin(s: number): number {
  let b = 0;
  while (b < WIND_BINS.length - 1 && s >= WIND_BINS[b + 1]) b++;
  return b;
}

export function windRose(
  speed: (number | null)[],
  dir: (number | null)[],
  month: number | null = null,
): WindRose {
  const share = Array.from({ length: 16 }, () => new Array<number>(WIND_BINS.length).fill(0));
  const lo = month === null ? 0 : MONTH_START_HOUR[month];
  const hi = month === null ? Math.min(speed.length, dir.length) : Math.min(MONTH_START_HOUR[month + 1], speed.length, dir.length);
  let total = 0;
  let sum = 0;
  for (let h = lo; h < hi; h++) {
    const s = speed[h];
    const d = dir[h];
    if (typeof s !== "number" || typeof d !== "number" || !Number.isFinite(s) || !Number.isFinite(d)) continue;
    const sector = Math.round((((d % 360) + 360) % 360) / 22.5) % 16;
    share[sector][speedBin(s)]++;
    total++;
    sum += s;
  }
  let best = -1;
  let bestN = 0;
  for (let d = 0; d < 16; d++) {
    const n = share[d].reduce((a, b) => a + b, 0);
    if (n > bestN) {
      bestN = n;
      best = d;
    }
    for (let b = 0; b < share[d].length; b++) share[d][b] = total ? share[d][b] / total : 0;
  }
  return { share, total, prevailing: best >= 0 ? best : null, meanSpeed: total ? sum / total : null };
}

// ---- temperature colour scale (diverging: cold blue, neutral, warm red) ----
export const TEMP_DOMAIN: [number, number] = [-10, 40];
const TEMP_STOPS: [number, string][] = [
  [-10, "#2b3f8f"],
  [0, "#4f86c6"],
  [8, "#a4c6e6"],
  [15, "#e9edf1"],
  [22, "#f6c98d"],
  [30, "#ec8446"],
  [40, "#a5281c"],
];
export const TEMP_STOP_LIST = TEMP_STOPS;

function hex(c: string): [number, number, number] {
  return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
}

export function tempColour(t: number | null | undefined): string {
  if (typeof t !== "number" || !Number.isFinite(t)) return "#9ca3af";
  const v = Math.max(TEMP_STOPS[0][0], Math.min(TEMP_STOPS[TEMP_STOPS.length - 1][0], t));
  let i = 0;
  while (i < TEMP_STOPS.length - 2 && v > TEMP_STOPS[i + 1][0]) i++;
  const [t0, c0] = TEMP_STOPS[i];
  const [t1, c1] = TEMP_STOPS[i + 1];
  const f = (v - t0) / (t1 - t0);
  const a = hex(c0);
  const b = hex(c1);
  const out = a.map((x, k) => Math.round(x + (b[k] - x) * f));
  return `rgb(${out[0]},${out[1]},${out[2]})`;
}

// ---- comfort ----
export interface ComfortMonth {
  cold: number;
  comfortable: number;
  hot: number;
  unknown: number;
}
export function comfortCounts(temps: (number | null)[], lo = 18, hi = 26): ComfortMonth[] {
  return MONTH_NAMES.map((_, m) => {
    const c: ComfortMonth = { cold: 0, comfortable: 0, hot: 0, unknown: 0 };
    const end = Math.min(MONTH_START_HOUR[m + 1], temps.length);
    for (let h = MONTH_START_HOUR[m]; h < end; h++) {
      const t = temps[h];
      if (typeof t !== "number" || !Number.isFinite(t)) c.unknown++;
      else if (t < lo) c.cold++;
      else if (t > hi) c.hot++;
      else c.comfortable++;
    }
    return c;
  });
}

export function typicalYearLabel(months: number[] | undefined): string {
  if (!months || !months.length) return "";
  return months.map((y, i) => `${MONTH_NAMES[i]} ${y}`).join(", ");
}

export function compassLabel(sector: number | null): string {
  return sector === null ? "–" : COMPASS16[sector];
}
