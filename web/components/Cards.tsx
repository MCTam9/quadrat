"use client";

import type { ReactNode } from "react";
import type { Metrics } from "@/lib/types";
import { asNum, num, pct } from "@/lib/format";
import { constraintGroups, LANDUSE_COLOURS, LANDUSE_LABELS } from "@/lib/layers";

/** A plain section: a heading and its content, separated by space. `boxed` is for the one thing
 *  that needs attention (thin data), so the box means something. */
export function Card({
  title,
  children,
  dim,
  loading,
  warn,
  boxed,
  major,
}: {
  title: string;
  children: ReactNode;
  dim?: boolean;
  loading?: boolean;
  /** The figures in this section rest on incomplete data. */
  warn?: string | null;
  boxed?: boolean;
  /** Heavier heading for the sections that matter most. */
  major?: boolean;
}) {
  const framed = boxed || !!warn;
  return (
    <section className={framed ? "border border-edge p-3" : ""} aria-busy={loading}>
      <h3 className={`mb-2 flex items-center gap-2 ${major ? "wide text-base font-semibold" : "text-sm font-semibold text-graphite"}`}>
        {title}
        {warn && (
          <span className="ml-auto flex items-center gap-1.5 text-xs font-normal text-graphite" title={warn}>
            <span className="missing-hatch inline-block h-2.5 w-2.5 border border-rule" aria-hidden />
            Limited data
          </span>
        )}
      </h3>
      {warn && <p className="mb-2 text-xs leading-snug text-graphite">{warn}</p>}
      <div className={`transition-opacity ${dim ? "opacity-50" : ""}`}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, unit, title }: { label: string; value: ReactNode; unit?: string; title?: string }) {
  return (
    <div title={title}>
      <div className="text-xs text-graphite">{label}</div>
      <div className="text-base font-semibold nums">
        {value}
        {unit && <span className="ml-0.5 text-xs font-normal text-graphite">{unit}</span>}
      </div>
    </div>
  );
}

function Skel() {
  return (
    <div className="grid grid-cols-3 gap-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="space-y-1.5">
          <div className="skeleton h-3 w-10" />
          <div className="skeleton h-5 w-14" />
        </div>
      ))}
    </div>
  );
}

// ESA WorldCover classes, reported by the land-cover layer as `landcover_class_<code>_fraction`.
const WORLDCOVER: Record<string, string> = {
  "10": "Tree cover", "20": "Shrubland", "30": "Grassland", "40": "Cropland", "50": "Built-up",
  "60": "Bare ground", "70": "Snow and ice", "80": "Water", "90": "Wetland", "95": "Mangroves", "100": "Moss and lichen",
};

function prettyKey(k: string) {
  const wc = k.match(/^landcover_class_(\d+)_fraction$/);
  if (wc) return `${WORLDCOVER[wc[1]] ?? `Class ${wc[1]}`} (satellite)`;
  const s = k
    .replace(/_km_km2$/, " (km/km²)")
    .replace(/_km2$/, " (km²)")
    .replace(/_km$/, " (km)")
    .replace(/_m$/, " (m)")
    .replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const isFraction = (k: string) => /_fraction$|_share$/.test(k);

/** Render scalar metrics not shown explicitly, so new backend keys still surface. */
function Extras({ m, skip }: { m?: Metrics; skip: string[] }) {
  if (!m) return null;
  const rows = Object.entries(m).filter(
    ([k, v]) => !skip.includes(k) && (typeof v === "string" || typeof v === "number" || typeof v === "boolean"),
  );
  if (!rows.length) return null;
  return (
    <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-graphite">{prettyKey(k)}</dt>
          <dd className="text-right nums">{typeof v === "number" ? (isFraction(k) ? `${Math.round(v * 100)} %` : num(v, 2)) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

interface CardProps {
  m?: Metrics;
  loading: boolean;
  stale: boolean;
}

/** Density figures the schedule does not show, so new backend keys still surface. */
export function DensityMore({ m }: { m?: Metrics }) {
  const known = ["gsi", "fsi", "fsi_coverage", "fsi_source", "building_count", "height_source_shares"];
  if (!m || !Object.entries(m).some(([k, v]) => !known.includes(k) && ["string", "number", "boolean"].includes(typeof v))) return null;
  return (
    <Card title="More density figures">
      <Extras m={m} skip={known} />
    </Card>
  );
}

export function OrientationRose({ bins, centres }: { bins: number[]; centres: number[] }) {
  const max = Math.max(1, ...bins);
  const R = 52;
  // Bearings are axial (0-180); mirror to a full rose.
  const wedges = bins.flatMap((b, i) => {
    const w = (centres[1] - centres[0] || 180 / bins.length) / 2;
    return [0, 180].map((off) => {
      const a0 = ((centres[i] + off - w - 90) * Math.PI) / 180;
      const a1 = ((centres[i] + off + w - 90) * Math.PI) / 180;
      const r = (b / max) * R;
      const p = (a: number) => `${(60 + r * Math.cos(a)).toFixed(2)},${(60 + r * Math.sin(a)).toFixed(2)}`;
      return <path key={`${i}-${off}`} d={`M60,60 L${p(a0)} L${p(a1)} Z`} fill="var(--ink)" fillOpacity="0.8" />;
    });
  });
  return (
    <svg viewBox="0 0 120 120" className="h-28 w-28 shrink-0" role="img" aria-label="Street orientation rose">
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--rule)" />
      <circle cx="60" cy="60" r={R / 2} fill="none" stroke="var(--rule)" strokeDasharray="2 3" />
      {wedges}
      <text x="60" y="9" textAnchor="middle" fontSize="11" fill="var(--graphite)">N</text>
    </svg>
  );
}

export function StreetsCard({ m, loading, stale }: CardProps) {
  const known = ["intersection_count", "intersection_density_km2", "street_length_km", "dead_end_share", "orientation_entropy_nats", "orientation_order_phi", "orientation_bins", "orientation_bin_centers_deg"];
  const bins = Array.isArray(m?.orientation_bins) ? (m.orientation_bins as number[]) : null;
  const centres = Array.isArray(m?.orientation_bin_centers_deg) ? (m.orientation_bin_centers_deg as number[]) : null;
  return (
    <Card title="Streets" major dim={stale} loading={loading}>
      {!m ? (
        <Skel />
      ) : (
        <>
          <div className="flex items-center gap-3">
            {bins && centres && bins.length > 1 && centres.length === bins.length && <OrientationRose bins={bins} centres={centres} />}
            <div className="grid flex-1 grid-cols-2 gap-3">
              <Stat label="Intersections" value={asNum(m.intersection_count) ?? "–"} />
              <Stat label="Density" value={num(m.intersection_density_km2, 0)} unit="/km²" />
              <Stat label="Length" value={num(m.street_length_km, 2)} unit="km" />
              <Stat label="Dead ends" value={pct(m.dead_end_share)} />
              <Stat label="Grid order" value={num(m.orientation_order_phi, 2)} title="1 = perfect grid, 0 = no preferred direction" />
            </div>
          </div>
          <Extras m={m} skip={known} />
        </>
      )}
    </Card>
  );
}

export function LandUseCard({ m, loading, stale }: CardProps) {
  const parts = m
    ? Object.entries(m)
        .map(([k, v]) => {
          const mt = k.match(/^landuse_(.+)_fraction$/);
          return mt && mt[1] !== "unmapped" && typeof v === "number" && v > 0 ? { name: mt[1], v } : null;
        })
        .filter((x): x is { name: string; v: number } => !!x)
        .sort((a, b) => b.v - a.v)
    : [];
  const colour = (n: string) => LANDUSE_COLOURS[n] ?? LANDUSE_COLOURS.other;
  const label = (n: string) => LANDUSE_LABELS[n] ?? prettyKey(n);
  const unmapped = asNum(m?.landuse_unmapped_fraction) ?? 0;
  return (
    <Card
      title="Land use"
      major
      dim={stale}
      loading={loading}
      warn={
        m && m.landuse_degraded
          ? `Only ${Math.round((1 - (asNum(m.landuse_unmapped_fraction) ?? 1)) * 100)}% of the site has mapped land use; the hatched part of the bar is unmapped.`
          : null
      }
    >
      {!m ? (
        <div className="skeleton h-4 w-full" />
      ) : (
        <>
          <div className="flex h-3.5 overflow-hidden bg-rule" role="img" aria-label="Land use share">
            {parts.map((p) => (
              <div key={p.name} style={{ width: `${p.v * 100}%`, background: colour(p.name) }} title={`${label(p.name)} ${pct(p.v)}`} />
            ))}
            {unmapped > 0.005 && <div className="missing-hatch" style={{ width: `${unmapped * 100}%` }} title={`Not mapped ${pct(unmapped)}`} />}
          </div>
          <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {parts.map((p) => (
              <li key={p.name} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 shrink-0" style={{ background: colour(p.name) }} />
                <span>{label(p.name)}</span>
                <span className="ml-auto whitespace-nowrap nums text-graphite">{pct(p.v)}</span>
              </li>
            ))}
            {unmapped > 0.005 && (
              <li className="flex items-center gap-1.5">
                <span className="missing-hatch h-2.5 w-2.5 shrink-0" />
                Not mapped
                <span className="ml-auto whitespace-nowrap nums text-graphite">{pct(unmapped)}</span>
              </li>
            )}
          </ul>
          {!parts.length && <p className="text-xs text-graphite">No land-use data in this area.</p>}
          <Extras m={m} skip={["landuse_degraded", ...Object.keys(m).filter((k) => /^landuse_.+_fraction$/.test(k))]} />
        </>
      )}
    </Card>
  );
}

export function TerrainCard({ m, loading, stale }: CardProps) {
  const known = ["elevation_min_m", "elevation_max_m", "elevation_mean_m", "elevation_range_m", "slope_mean_deg", "dominant_aspect", "terrain_model", "terrain_model_note"];
  return (
    <Card title="Terrain" dim={stale} loading={loading}>
      {!m ? (
        <Skel />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Elevation" value={`${num(m.elevation_min_m, 0)}–${num(m.elevation_max_m, 0)}`} unit="m" />
            <Stat label="Range" value={num(m.elevation_range_m, 1)} unit="m" />
            <Stat label="Slope" value={num(m.slope_mean_deg, 1)} unit="°" />
            <Stat label="Aspect" value={typeof m.dominant_aspect === "string" ? m.dominant_aspect : num(m.dominant_aspect, 0)} />
          </div>
          {(typeof m.terrain_model === "string" || typeof m.terrain_model_note === "string") && (
            <p className="mt-2 text-xs text-graphite">
              {[m.terrain_model, m.terrain_model_note].filter((x) => typeof x === "string" && x).join(". ")}
            </p>
          )}
          <Extras m={m} skip={known} />
        </>
      )}
    </Card>
  );
}

export function AccessCard({ m, loading, stale }: CardProps) {
  const known = ["walk_reach_ratio_10min", "amenity_category_count_10min", "nearest_transit_distance_m"];
  return (
    <Card title="Access" dim={stale} loading={loading}>
      {!m ? (
        <Skel />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="10-minute walk reach" value={pct(m.walk_reach_ratio_10min)} />
            <Stat label="Amenity types" value={asNum(m.amenity_category_count_10min) ?? "–"} />
            <Stat label="Nearest transit" value={num(m.nearest_transit_distance_m, 0)} unit="m" />
          </div>
          <Extras m={m} skip={known} />
        </>
      )}
    </Card>
  );
}

export function ClimateCard({ m, loading, stale }: CardProps) {
  const known = ["hdd_18c", "cdd_18c", "ghi_kwh_m2_year", "mean_temp_c", "prevailing_wind_direction_deg", "prevailing_wind_frequency"];
  return (
    <Card title="Climate" dim={stale} loading={loading}>
      {!m ? (
        <Skel />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Mean temperature" value={num(m.mean_temp_c, 1)} unit="°C" />
            <Stat label="Heating degree days" value={num(m.hdd_18c, 0)} title="Base 18 °C" />
            <Stat label="Cooling degree days" value={num(m.cdd_18c, 0)} title="Base 18 °C" />
            <Stat label="Solar (GHI)" value={num(m.ghi_kwh_m2_year, 0)} unit="kWh/m²" />
            <Stat label="Wind from" value={num(m.prevailing_wind_direction_deg, 0)} unit="°" />
            <Stat label="Wind share" value={pct(m.prevailing_wind_frequency)} />
          </div>
          <Extras m={m} skip={known} />
        </>
      )}
    </Card>
  );
}

/** Planning constraints that touch the site, from the preview's constraints layer. */
export function ConstraintsCard({ fc }: { fc?: GeoJSON.FeatureCollection | null }) {
  const groups = constraintGroups(fc);
  if (!groups.length) return null;
  return (
    <Card title="Planning constraints" boxed major>
      <ul className="space-y-1.5 text-xs">
        {groups.map((g) => (
          <li key={g.dataset}>
            <span className="font-semibold">{g.label}</span>
            <span className="ml-1.5 text-graphite nums">{g.count}</span>
            {g.names.length > 0 && (
              <span className="line-clamp-2 block text-graphite">
                {g.names.slice(0, 4).join(", ")}
                {g.names.length > 4 ? ` and ${g.names.length - 4} more` : ""}
              </span>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
