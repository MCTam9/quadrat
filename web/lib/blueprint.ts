import { BLUEPRINT } from "./layers";

type Kind = "fill" | "line" | "text" | "halo";

/** Where a basemap colour lands on the blueprint, by layer id and how light the original was (0 to 1). */
export function blueprintColour(layerId: string, kind: Kind, luma: number): string {
  if (kind === "halo") return BLUEPRINT;
  if (kind === "text") return luma > 0.3 ? "#bdbdbd" : "#8f8f8f";
  if (/^water|^aeroway-area/.test(layerId)) return "#0e0e0e";
  if (/^landcover|^landuse/.test(layerId)) return luma > 0.09 ? "#1f1f1f" : "#1b1b1b";
  if (layerId === "building") return "#2a2a2a";
  if (kind === "fill") return luma > 0.09 ? "#1f1f1f" : "#0e0e0e";
  // lines: roads and rail darker than the sheet, casings and boundaries lighter
  return luma < 0.05 ? "#0a0a0a" : luma < 0.2 ? "#2e2e2e" : "#474747";
}

/** Relative luminance of a CSS colour, or null when it cannot be parsed. */
export function lumaOf(css: string): number | null {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return null;
  ctx.fillStyle = "#010203";
  ctx.fillStyle = css;
  const v = ctx.fillStyle;
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(v) ?? /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(v);
  if (!m) return null;
  const [r, g, b] = [1, 2, 3].map((i) => (m[0].startsWith("#") ? parseInt(m[i], 16) : Number(m[i])) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
