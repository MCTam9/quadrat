export type Metrics = Record<string, unknown>;

export interface LayerEvent {
  layer: string;
  provider?: string;
  features?: number;
  coverage?: number | null;
  ok: boolean;
}

export interface ReadyEvent {
  site_id: string;
  epsg: number;
  centre: [number, number];
  padded_half_width_m: number;
  bbox_wgs84?: [number, number, number, number];
}

export interface Analysis {
  aoi?: Record<string, unknown>;
  metrics: {
    street?: Metrics;
    fabric?: Metrics;
    landuse?: Metrics;
    access?: Metrics;
    terrain?: Metrics;
    climate?: Metrics;
    constraints?: Metrics;
    errors?: Record<string, string>;
    [k: string]: unknown;
  };
  assessment?: { coverage?: unknown; degraded?: boolean; warnings?: string[] };
  layers?: Record<string, { provider?: string; coverage?: number | null; degraded?: boolean; notes?: string }>;
}

export interface Preview {
  square?: GeoJSON.Feature;
  buildings: GeoJSON.FeatureCollection;
  streets: GeoJSON.FeatureCollection;
  landuse?: GeoJSON.FeatureCollection;
  contours?: GeoJSON.FeatureCollection;
  contour_interval_m?: number | null;
  constraints?: GeoJSON.FeatureCollection;
}

export interface ClimateSource {
  name: string;
  period: string;
  grid_point_lonlat: [number, number];
  elevation_m: number | null;
  licence: string;
  note: string;
}

export type HourlyVar =
  | "temperature_c"
  | "dew_point_c"
  | "relative_humidity_pct"
  | "ghi_wm2"
  | "dni_wm2"
  | "dhi_wm2"
  | "wind_speed_ms"
  | "wind_direction_deg"
  | "cloud_cover_pct"
  | "precipitation_mm";

export interface ClimateMonth {
  month: number | string;
  temp_mean_c: number | null;
  temp_mean_daily_max_c: number | null;
  temp_mean_daily_min_c: number | null;
  temp_record_max_c: number | null;
  temp_record_min_c: number | null;
  precip_mm: number | null;
  ghi_kwh_m2: number | null;
  wind_mean_ms: number | null;
  rh_mean_pct: number | null;
}

export interface Climate {
  source: ClimateSource;
  timezone: { name: string | null; standard_offset_h: number; approximate: boolean };
  typical_year: {
    months_from_years: number[];
    method: string;
    hourly: Record<HourlyVar, (number | null)[]>;
  };
  monthly: ClimateMonth[];
  annual: { hdd_18c: number | null; cdd_18c: number | null; ghi_kwh_m2: number | null; mean_temp_c: number | null; precip_mm: number | null };
}

export const EXPORT_FORMATS = [
  { id: "dxf", label: "DXF", hint: "AutoCAD" },
  { id: "3dm", label: "3DM", hint: "Rhino" },
  { id: "svg", label: "SVG", hint: "Vector" },
  { id: "geojson", label: "GeoJSON", hint: "GIS" },
  { id: "glb", label: "GLB", hint: "3D" },
  { id: "obj", label: "OBJ", hint: "3D" },
  { id: "gpkg", label: "GPKG", hint: "QGIS" },
  { id: "epw", label: "EPW", hint: "Ladybug / EnergyPlus" },
] as const;
