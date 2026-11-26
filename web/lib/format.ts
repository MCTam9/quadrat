export function num(v: unknown, digits = 1): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "–";
}
export function pct(v: unknown, digits = 0): string {
  return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(digits)} %` : "–";
}
export function asNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
export function time(d: Date | null): string {
  return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "–";
}
/** "840 ms" under a second, "2.4 s" above; "" when unknown. */
export function duration(ms: unknown): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
