import { classifySource, HEIGHT_CATEGORIES } from "./buildings";
import { BUILDING_TAG_USE, BUILDING_USE, LANDUSE, type BuildingUseId } from "./vocab.generated";

export type ColourMode = "source" | "height" | "type" | "none";
export type Overlay = "landuse" | "streets" | "contours" | "constraints" | "sun" | "wind";

export interface LayerState {
  mode: ColourMode;
  overlays: Record<Overlay, boolean>;
}

export const DEFAULT_LAYERS: LayerState = {
  mode: "none",
  overlays: { landuse: false, streets: false, contours: false, constraints: false, sun: false, wind: false },
};

export const OVERLAYS: { id: Overlay; label: string; hint: string }[] = [
  { id: "landuse", label: "Land use", hint: "fills by class" },
  { id: "streets", label: "Streets", hint: "by highway class" },
  { id: "contours", label: "Contours", hint: "elevation lines" },
  { id: "constraints", label: "Planning constraints", hint: "GB only" },
  { id: "sun", label: "Sun path", hint: "solstices and equinox" },
  { id: "wind", label: "Wind rose", hint: "from climate data" },
];

export const MODES: { id: ColourMode; label: string }[] = [
  { id: "none", label: "No colour" },
  { id: "source", label: "Height source" },
  { id: "height", label: "Height" },
  { id: "type", label: "Building type" },
];

// v2: the default colour mode changed to "No colour".
const KEY = "sce.layers.v2";

/** Parse a stored value defensively; anything unexpected falls back to defaults. */
export function parseLayers(raw: string | null): LayerState {
  if (!raw) return DEFAULT_LAYERS;
  try {
    const j = JSON.parse(raw) as Partial<LayerState>;
    const mode = MODES.some((m) => m.id === j.mode) ? (j.mode as ColourMode) : DEFAULT_LAYERS.mode;
    const overlays = { ...DEFAULT_LAYERS.overlays };
    for (const o of OVERLAYS) if (typeof j.overlays?.[o.id] === "boolean") overlays[o.id] = j.overlays[o.id];
    return { mode, overlays };
  } catch {
    return DEFAULT_LAYERS;
  }
}
export function loadLayers(): LayerState {
  try {
    return parseLayers(localStorage.getItem(KEY));
  } catch {
    return DEFAULT_LAYERS;
  }
}
export function saveLayers(s: LayerState) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable */
  }
}

// ---- map palette: the white sheet and the dark sheet ----
export const BASEMAP = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
} as const;
export const RED_LINE = "#e0261b";
/** Dark sheet: neutral charcoal, so the only colour on the map is data and the red line. */
export const BLUEPRINT = "#161616";

export interface MapPalette {
  /** "No colour": site buildings as solid ink. */
  ink: string;
  /** Context massing outside the square: pale graphite. */
  context: string;
  /** Building outline and text halo, the sheet colour. */
  halo: string;
  outline: string;
  streets: string;
  contour: string;
  contourLabel: string;
  heightRamp: string[];
}
export const PALETTE: Record<"light" | "dark", MapPalette> = {
  light: {
    ink: "#000000",
    context: "#c3c5bf",
    halo: "#ffffff",
    outline: "#ffffff",
    streets: "#6b7069",
    contour: "#92400e",
    contourLabel: "#78350f",
    heightRamp: ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"],
  },
  dark: {
    ink: "#ffffff",
    context: "#5c5c5c",
    halo: BLUEPRINT,
    outline: "rgba(255,255,255,0.45)",
    streets: "#a3a3a3",
    contour: "#e0b48a",
    contourLabel: "#f1d3b0",
    heightRamp: ["#35577a", "#4f7ba6", "#6f9fcb", "#93bee3", "#bddbf2", "#e4f1fb", "#ffffff"],
  },
};
export const palette = (dark: boolean) => PALETTE[dark ? "dark" : "light"];

/** Missing data is loud on purpose: rose fill with a crimson hatch, never a quiet grey
 *  that reads as "a building with a dull value". */
export const MISSING_FILL = "#fecdd3";
export const MISSING_LINE = "#e11d48";
/** "No colour" mode paints site buildings in ink: black on the sheet, white on the dark sheet. */
export const NEUTRAL_BUILDING = PALETTE.light.ink;

/** Buildings whose attribute for this colour mode is missing (drawn hatched). */
export function missingFilter(mode: ColourMode): unknown[] {
  if (mode === "source") return ["==", ["get", "hcat"], "unknown"];
  if (mode === "height") return ["<=", ["get", "h"], 0];
  if (mode === "type") return ["==", ["get", "btype"], "unspecified"];
  // Not ["==", 1, 0]: MapLibre reads that as a legacy filter and throws.
  return ["boolean", false];
}

export type LegendItem = { label: string; color: string; hatch?: boolean };
const MISSING_ITEM = (label: string): LegendItem => ({ label, color: MISSING_LINE, hatch: true });
export const HEIGHT_BREAKS = [3, 6, 10, 15, 25, 40]; // metres; bins: <3, 3-6, ... 40+
export const HEIGHT_COLOURS = PALETTE.light.heightRamp;

export function heightBin(h: number | null | undefined): number {
  if (typeof h !== "number" || !Number.isFinite(h) || h <= 0) return -1;
  let i = 0;
  while (i < HEIGHT_BREAKS.length && h >= HEIGHT_BREAKS[i]) i++;
  return i;
}
export function heightLegend(dark = false): LegendItem[] {
  const ramp = palette(dark).heightRamp;
  const out = ramp.map((color, i) => ({
    color,
    label: i === 0 ? `< ${HEIGHT_BREAKS[0]} m` : i === HEIGHT_BREAKS.length ? `${HEIGHT_BREAKS[i - 1]} m +` : `${HEIGHT_BREAKS[i - 1]} to ${HEIGHT_BREAKS[i]} m`,
  }));
  return [...out, MISSING_ITEM("No height data")];
}

// ---- building type: the vocabulary's building-use classes, plus "unspecified" for no evidence ----
export type BuildingType = BuildingUseId | "unspecified";

export const BUILDING_TYPES: { id: BuildingType; label: string; color: string }[] = [
  ...BUILDING_USE.map((u) => ({ id: u.id as BuildingType, label: u.label, color: u.colour })),
  { id: "unspecified", label: "No type data (no tag or evidence)", color: MISSING_FILL },
];

export function classifyBuilding(tag: unknown): BuildingType {
  const t = typeof tag === "string" ? tag.trim().toLowerCase() : "";
  if (!t || t === "yes") return "unspecified";
  return BUILDING_TAG_USE[t] ?? "other";
}

// ---- MapLibre colour expressions ----
export function buildingColour(mode: ColourMode, dark = false): unknown[] | string {
  const pal = palette(dark);
  if (mode === "none") return pal.ink;
  if (mode === "height") {
    const e: unknown[] = ["case", ["<=", ["get", "h"], 0], MISSING_FILL, ["step", ["get", "h"], pal.heightRamp[0]]];
    const step = e[3] as unknown[];
    HEIGHT_BREAKS.forEach((b, i) => step.push(b, pal.heightRamp[i + 1]));
    return e;
  }
  const [prop, items] =
    mode === "type" ? (["btype", BUILDING_TYPES] as const) : (["hcat", HEIGHT_CATEGORIES.map((c) => ({ id: c.id, color: c.colour }))] as const);
  const e: unknown[] = ["match", ["get", prop]];
  for (const c of items) e.push(c.id, c.id === "unknown" || c.id === "unspecified" ? MISSING_FILL : c.color);
  e.push(MISSING_FILL);
  return e;
}

// ---- overlays ----
export const LANDUSE_COLOURS: Record<string, string> = Object.fromEntries(LANDUSE.map((l) => [l.id, l.colour]));
export const LANDUSE_LABELS: Record<string, string> = Object.fromEntries(LANDUSE.map((l) => [l.id, l.label]));

export const STREET_CLASSES: { id: string; label: string; color: string; colorDark: string; width: number; match: string[] }[] = [
  { id: "major", label: "Motorway, trunk and primary", color: "#c2410c", colorDark: "#fb923c", width: 3, match: ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"] },
  { id: "secondary", label: "Secondary and tertiary", color: "#d97706", colorDark: "#fbbf24", width: 2.2, match: ["secondary", "secondary_link", "tertiary", "tertiary_link"] },
  { id: "local", label: "Residential and service", color: "#475569", colorDark: "#b6c6d8", width: 1.4, match: ["residential", "unclassified", "living_street", "service"] },
  { id: "active", label: "Footway, cycleway and path", color: "#15803d", colorDark: "#4ade80", width: 1.2, match: ["footway", "pedestrian", "path", "cycleway", "steps", "track", "bridleway"] },
];
export function streetClass(hw: unknown): string {
  const h = typeof hw === "string" ? hw : "";
  return STREET_CLASSES.find((c) => c.match.includes(h))?.id ?? "local";
}

export const CONSTRAINT_STYLES: Record<string, { label: string; color: string; colorDark: string }> = {
  "conservation-area": { label: "Conservation area", color: "#15803d", colorDark: "#4ade80" },
  "listed-building": { label: "Listed building", color: "#9a3412", colorDark: "#fb923c" },
  "flood-risk-zone": { label: "Flood risk zone", color: "#1d4ed8", colorDark: "#7dd3fc" },
  "listed-building-outline": { label: "Listed building outline", color: "#9a3412", colorDark: "#fb923c" },
  "article-4-direction-area": { label: "Article 4 direction area", color: "#a16207", colorDark: "#facc15" },
};
export const CONSTRAINT_OTHER = { label: "Other constraint", color: "#7e22ce", colorDark: "#d8b4fe" };
export function constraintStyle(ds: unknown) {
  return CONSTRAINT_STYLES[String(ds)] ?? CONSTRAINT_OTHER;
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
export const emptyFc = () => EMPTY;

/** Add derived props used by map expressions (street class, contour major flag, constraint style). */
export function annotateStreets(fc?: GeoJSON.FeatureCollection | null): GeoJSON.FeatureCollection {
  if (!fc) return EMPTY;
  return { ...fc, features: fc.features.map((f) => ({ ...f, properties: { ...f.properties, sclass: streetClass(f.properties?.highway) } })) };
}
export function annotateContours(fc: GeoJSON.FeatureCollection | undefined | null, interval: number | null | undefined): GeoJSON.FeatureCollection {
  if (!fc) return EMPTY;
  const major = interval && interval > 0 ? interval * 5 : 0;
  return {
    ...fc,
    features: fc.features.map((f) => {
      const e = Number(f.properties?.elevation_m);
      const isMajor = major > 0 && Number.isFinite(e) && Math.abs(e / major - Math.round(e / major)) < 1e-6;
      return { ...f, properties: { ...f.properties, major: isMajor ? 1 : 0, label: Number.isFinite(e) ? `${Math.round(e)} m` : "" } };
    }),
  };
}
export function annotateConstraints(fc?: GeoJSON.FeatureCollection | null): GeoJSON.FeatureCollection {
  if (!fc) return EMPTY;
  return {
    ...fc,
    features: fc.features.map((f) => {
      const ds = String(f.properties?.dataset ?? "");
      const st = constraintStyle(ds);
      return { ...f, properties: { ...f.properties, ckey: ds in CONSTRAINT_STYLES ? ds : "other", label: `${f.properties?.name ?? st.label}`, dsLabel: st.label } };
    }),
  };
}

const USE_IDS = new Set<string>(BUILDING_USE.map((u) => u.id));

/** Legend rows for a colour mode, with the missing-data row shown hatched. */
export function modeLegend(mode: ColourMode, dark = false): { title: string; items: LegendItem[] } | null {
  if (mode === "source")
    return {
      title: "Building height source",
      items: HEIGHT_CATEGORIES.map((c) => (c.id === "unknown" ? MISSING_ITEM(c.label) : { label: c.label, color: c.colour })),
    };
  if (mode === "height") return { title: "Building height", items: heightLegend(dark) };
  if (mode === "type")
    return {
      title: "Building type",
      items: BUILDING_TYPES.map((c) => (c.id === "unspecified" ? MISSING_ITEM(c.label) : c)),
    };
  return null;
}

/** Building type: the API's `use` (tagged or inferred, see sce/building_use.py), else the raw tag. */
export function buildingType(p: Record<string, unknown>): BuildingType {
  if (typeof p.use === "string" && USE_IDS.has(p.use)) return p.use as BuildingType;
  return classifyBuilding(p.building);
}

export type UseSource = "tag" | "tags" | "poi" | "landuse" | "none";
export const USE_SOURCE_LABELS: Record<UseSource, string> = {
  tag: "building tag",
  tags: "shop/office/amenity tags",
  poi: "ground-floor businesses inside",
  landuse: "land-use zone",
  none: "unknown",
};

/** Share of buildings per type evidence, for the legend's honesty line. */
export function typeSourceShares(fc: GeoJSON.FeatureCollection | null): { id: UseSource; share: number }[] {
  const feats = fc?.features ?? [];
  if (!feats.length) return [];
  const counts: Record<UseSource, number> = { tag: 0, tags: 0, poi: 0, landuse: 0, none: 0 };
  for (const f of feats) {
    const src = f.properties?.use_source as string | undefined;
    if (src === "tag" || src === "tags" || src === "poi" || src === "landuse") counts[src] += 1;
    else if (f.properties?.btype && f.properties.btype !== "unspecified") counts.tag += 1;
    else counts.none += 1;
  }
  return (Object.keys(counts) as UseSource[])
    .map((id) => ({ id, share: counts[id] / feats.length }))
    .filter((x) => x.share > 0);
}

/** Context buildings need only a height for massing. */
export function annotateContext(fc?: GeoJSON.FeatureCollection | null): GeoJSON.FeatureCollection {
  if (!fc) return EMPTY;
  return {
    ...fc,
    features: fc.features.map((f) => {
      const h = f.properties?.height_m;
      return { ...f, properties: { ...f.properties, h: typeof h === "number" && h > 0 ? h : 0 } };
    }),
  };
}

/** Add derived props used by map expressions: hcat (height source), btype (building use), h (metres, 0 = unknown). */
export function annotateBuildings(fc: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  return {
    ...fc,
    features: fc.features.map((f) => {
      const p = (f.properties ?? {}) as Record<string, unknown>;
      return {
        ...f,
        properties: {
          ...p,
          btype: buildingType(p),
          hcat: classifySource(p.height_source, p.height_m),
          h: typeof p.height_m === "number" ? p.height_m : 0,
        },
      };
    }),
  };
}

export const sentenceCase = (id: string) => {
  const t = id.replace(/[-_]/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/** Planning constraints in the preview, grouped by dataset with their distinct names. */
export function constraintGroups(fc?: GeoJSON.FeatureCollection | null): { dataset: string; label: string; count: number; names: string[] }[] {
  const by = new Map<string, { count: number; names: Set<string> }>();
  for (const f of fc?.features ?? []) {
    const ds = String(f.properties?.dataset ?? "").trim();
    if (!ds) continue;
    const g = by.get(ds) ?? { count: 0, names: new Set<string>() };
    g.count += 1;
    const name = String(f.properties?.name ?? "").trim();
    if (name) g.names.add(name);
    by.set(ds, g);
  }
  return [...by].map(([dataset, g]) => ({ dataset, label: CONSTRAINT_STYLES[dataset]?.label ?? sentenceCase(dataset), count: g.count, names: [...g.names] }));
}
