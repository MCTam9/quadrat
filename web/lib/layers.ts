import { classifySource, HEIGHT_CATEGORIES } from "./buildings";

export type ColourMode = "source" | "height" | "type" | "none";
export type Overlay = "landuse" | "streets" | "contours" | "constraints" | "sun" | "wind";

export interface LayerState {
  mode: ColourMode;
  overlays: Record<Overlay, boolean>;
}

export const DEFAULT_LAYERS: LayerState = {
  mode: "source",
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
  { id: "source", label: "Height source" },
  { id: "height", label: "Height" },
  { id: "type", label: "Building type" },
  { id: "none", label: "No colour" },
];

const KEY = "sce.layers";

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

// ---- building height ramp (sequential, one hue) ----
export const UNKNOWN_GREY = "#aeb4be";
/** Missing data is loud on purpose: rose fill with a crimson hatch, never a quiet grey
 *  that reads as "a building with a dull value". */
export const MISSING_FILL = "#fecdd3";
export const MISSING_LINE = "#e11d48";
/** "No colour" mode: one neutral tone so the massing reads on its own. */
export const NEUTRAL_BUILDING = "#c9ccd1";

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
export const HEIGHT_COLOURS = ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"];

export function heightBin(h: number | null | undefined): number {
  if (typeof h !== "number" || !Number.isFinite(h) || h <= 0) return -1;
  let i = 0;
  while (i < HEIGHT_BREAKS.length && h >= HEIGHT_BREAKS[i]) i++;
  return i;
}
export function heightLegend(): { label: string; color: string }[] {
  const out = HEIGHT_COLOURS.map((color, i) => ({
    color,
    label: i === 0 ? `< ${HEIGHT_BREAKS[0]} m` : i === HEIGHT_BREAKS.length ? `${HEIGHT_BREAKS[i - 1]} m +` : `${HEIGHT_BREAKS[i - 1]} to ${HEIGHT_BREAKS[i]} m`,
  }));
  return [...out, MISSING_ITEM("No height data")];
}

// ---- building type ----
export type BuildingType = "residential" | "commercial" | "retail" | "industrial" | "civic" | "other" | "unspecified";

export const BUILDING_TYPES: { id: BuildingType; label: string; color: string }[] = [
  { id: "residential", label: "Residential", color: "#0072b2" },
  { id: "commercial", label: "Commercial / office", color: "#e69f00" },
  { id: "retail", label: "Retail", color: "#cc79a7" },
  { id: "industrial", label: "Industrial", color: "#d55e00" },
  { id: "civic", label: "Civic / education / religious", color: "#009e73" },
  { id: "other", label: "Other", color: "#56b4e9" },
  { id: "unspecified", label: "No type data (no tag or evidence)", color: MISSING_FILL },
];

const TYPE_MAP: Record<string, BuildingType> = {};
function reg(t: BuildingType, tags: string) {
  for (const k of tags.split(" ")) TYPE_MAP[k] = t;
}
reg("residential", "residential house detached semidetached_house terrace terraced_house apartments flats bungalow dormitory houseboat static_caravan cabin farm");
reg("commercial", "commercial office offices hotel bank");
reg("retail", "retail supermarket kiosk shop mall");
reg("industrial", "industrial warehouse factory manufacture service storage_tank");
reg("civic", "civic public government school university college kindergarten hospital church chapel cathedral mosque synagogue temple religious monastery fire_station train_station transportation museum library theatre sports_hall");

export function classifyBuilding(tag: unknown): BuildingType {
  const t = typeof tag === "string" ? tag.trim().toLowerCase() : "";
  if (!t || t === "yes") return "unspecified";
  return TYPE_MAP[t] ?? "other";
}

// ---- MapLibre colour expressions ----
export function buildingColour(mode: ColourMode): unknown[] | string {
  if (mode === "none") return NEUTRAL_BUILDING;
  if (mode === "height") {
    const e: unknown[] = ["case", ["<=", ["get", "h"], 0], MISSING_FILL, ["step", ["get", "h"], HEIGHT_COLOURS[0]]];
    const step = e[3] as unknown[];
    HEIGHT_BREAKS.forEach((b, i) => step.push(b, HEIGHT_COLOURS[i + 1]));
    return e;
  }
  const [prop, items, fallback] =
    mode === "type"
      ? (["btype", BUILDING_TYPES, MISSING_FILL] as const)
      : (["hcat", HEIGHT_CATEGORIES, MISSING_FILL] as const);
  const e: unknown[] = ["match", ["get", prop]];
  for (const c of items) e.push(c.id, c.id === "unknown" || c.id === "unspecified" ? MISSING_FILL : c.color);
  e.push(fallback);
  return e;
}

// ---- overlays ----
export const LANDUSE_COLOURS: Record<string, string> = {
  residential: "#f0b98d",
  commercial: "#e58fb0",
  industrial: "#a8a29e",
  civic: "#a78bfa",
  green_space: "#7fc98a",
  agriculture: "#d8d27c",
  water: "#6fb1e4",
  transport: "#8b9bb0",
  other: "#cbd5e1",
};
export const LANDUSE_LABELS: Record<string, string> = {
  residential: "Residential", commercial: "Commercial", industrial: "Industrial", civic: "Civic", green_space: "Green space",
  agriculture: "Agriculture", water: "Water", transport: "Transport", other: "Other",
};

export const STREET_CLASSES: { id: string; label: string; color: string; width: number; match: string[] }[] = [
  { id: "major", label: "Motorway / trunk / primary", color: "#c2410c", width: 3, match: ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"] },
  { id: "secondary", label: "Secondary / tertiary", color: "#d97706", width: 2.2, match: ["secondary", "secondary_link", "tertiary", "tertiary_link"] },
  { id: "local", label: "Residential / service", color: "#475569", width: 1.4, match: ["residential", "unclassified", "living_street", "service"] },
  { id: "active", label: "Footway / cycleway / path", color: "#15803d", width: 1.2, match: ["footway", "pedestrian", "path", "cycleway", "steps", "track", "bridleway"] },
];
export function streetClass(hw: unknown): string {
  const h = typeof hw === "string" ? hw : "";
  return STREET_CLASSES.find((c) => c.match.includes(h))?.id ?? "local";
}

export const CONSTRAINT_STYLES: Record<string, { label: string; color: string }> = {
  "conservation-area": { label: "Conservation area", color: "#15803d" },
  "listed-building": { label: "Listed building", color: "#9a3412" },
  "flood-risk-zone": { label: "Flood risk zone", color: "#1d4ed8" },
};
export const CONSTRAINT_OTHER = { label: "Other constraint", color: "#7e22ce" };
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

const USE_IDS = new Set<string>(["residential", "commercial", "retail", "industrial", "civic", "other"]);

/** Legend rows for a colour mode, with the missing-data row shown hatched. */
export function modeLegend(mode: ColourMode): { title: string; items: LegendItem[] } | null {
  if (mode === "source")
    return {
      title: "Building height source",
      items: HEIGHT_CATEGORIES.map((c) => (c.id === "unknown" ? MISSING_ITEM("No height data (drawn flat)") : c)),
    };
  if (mode === "height") return { title: "Building height", items: heightLegend() };
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

/** Add derived props used by map expressions: hcat (height source), btype (OSM building class), h (metres, 0 = unknown). */
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
