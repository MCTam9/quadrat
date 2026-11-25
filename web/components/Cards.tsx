"use client";

import type { ReactNode } from "react";
import type { Analysis, Metrics } from "@/lib/types";
import { asNum, num, pct } from "@/lib/format";

export function Card({
  title,
  children,
  dim,
  loading,
  warn,
}: {
  title: string;
  children: ReactNode;
  dim?: boolean;
  loading?: boolean;
  /** Shown as an amber badge: the figures in this card rest on incomplete data. */
  warn?: string | null;
}) {
  return (
    <section className={`rounded-xl border p-3 ${warn ? "border-amber-500/50" : "border-line"}`} aria-busy={loading}>
      <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {title}
        {warn && (
          <span
            className="ml-auto rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold normal-case tracking-normal text-amber-700 dark:text-amber-300"
            title={warn}
          >
            ▲ Limited data
          </span>
        )}
      </h3>
      {warn && <p className="mb-2 text-[11px] leading-snug text-amber-700 dark:text-amber-300">{warn}</p>}
      <div className={`transition-opacity ${dim ? "opacity-50" : ""}`}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, unit, title }: { label: string; value: ReactNode; unit?: string; title?: string }) {
  return (
    <div title={title}>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="text-base font-semibold tabular-nums">
        {value}
        {unit && <span className="ml-0.5 text-xs font-normal text-muted">{unit}</span>}
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

function prettyKey(k: string) {
  return k.replace(/_/g, " ");
}

/** Render scalar metrics not shown explicitly, so new backend keys still surface. */
function Extras({ m, skip }: { m?: Metrics; skip: string[] }) {
  if (!m) return null;
  const rows = Object.entries(m).filter(
    ([k, v]) => !skip.includes(k) && (typeof v === "string" || typeof v === "number" || typeof v === "boolean"),
  );
  if (!rows.length) return null;
  return (
    <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-t border-line pt-2 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{prettyKey(k)}</dt>
          <dd className="text-right tabular-nums">{typeof v === "number" ? num(v, 2) : String(v)}</dd>
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

function densityWarning(m: Metrics | undefined): string | null {
  if (!m) return null;
  const cov = asNum(m.fsi_coverage);
  if (m.fsi == null) return "FSI not computed: too few building heights are known for this site.";
  if (cov != null && cov < 0.4)
    return `Only ${Math.round(cov * 100)}% of building heights are known, so FSI uses a satellite average height (100 m cells) and is an estimate.`;
  if (cov != null && cov < 0.8) return `${Math.round((1 - cov) * 100)}% of buildings have no height; they count as zero floors in FSI.`;
  return null;
}

export function DensityCard({ m, loading, stale }: CardProps) {
  const known = ["gsi", "fsi", "fsi_coverage", "fsi_source", "building_count"];
  return (
    <Card title="Density" dim={stale} loading={loading} warn={densityWarning(m)}>
      {!m ? (
        <Skel />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="GSI" value={num(m.gsi, 2)} />
            <Stat
              label="FSI"
              value={num(m.fsi, 2)}
              title={typeof m.fsi_source === "string" ? m.fsi_source : undefined}
            />
            <Stat label="Buildings" value={asNum(m.building_count) ?? "–"} />
          </div>
          <p className="mt-2 text-xs text-muted" title={typeof m.fsi_source === "string" ? m.fsi_source : undefined}>
            {pct(m.fsi_coverage)} heights measured
            {typeof m.fsi_source === "string" && <span> · {m.fsi_source}</span>}
          </p>
          <Extras m={m} skip={known} />
        </>
      )}
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
      return <path key={`${i}-${off}`} d={`M60,60 L${p(a0)} L${p(a1)} Z`} fill="var(--accent)" fillOpacity="0.75" />;
    });
  });
  return (
    <svg viewBox="0 0 120 120" className="h-28 w-28 shrink-0" role="img" aria-label="Street orientation rose">
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--line)" />
      <circle cx="60" cy="60" r={R / 2} fill="none" stroke="var(--line)" strokeDasharray="2 3" />
      {wedges}
      <text x="60" y="8" textAnchor="middle" fontSize="8" fill="var(--muted)">N</text>
    </svg>
  );
}

export function StreetsCard({ m, loading, stale }: CardProps) {
  const known = ["intersection_count", "intersection_density_km2", "street_length_km", "dead_end_share", "orientation_entropy_nats", "orientation_order_phi", "orientation_bins", "orientation_bin_centers_deg"];
  const bins = Array.isArray(m?.orientation_bins) ? (m.orientation_bins as number[]) : null;
  const centres = Array.isArray(m?.orientation_bin_centers_deg) ? (m.orientation_bin_centers_deg as number[]) : null;
  return (
    <Card title="Streets" dim={stale} loading={loading}>
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
              <Stat label="Order φ" value={num(m.orientation_order_phi, 2)} title="1 = perfect grid, 0 = no preferred direction" />
            </div>
          </div>
          <Extras m={m} skip={known} />
        </>
      )}
    </Card>
  );
}

const LU_COLORS: Record<string, string> = {
  residential: "#f59e0b", commercial: "#ef4444", industrial: "#8b5cf6", civic: "#0ea5e9",
  green_space: "#22c55e", agriculture: "#a3e635", water: "#38bdf8", transport: "#64748b", other: "#d1d5db", unmapped: "#9ca3af",
};

export function LandUseCard({ m, loading, stale }: CardProps) {
  const parts = m
    ? Object.entries(m)
        .map(([k, v]) => {
          const mt = k.match(/^landuse_(.+)_fraction$/);
          return mt && typeof v === "number" && v > 0 ? { name: mt[1], v } : null;
        })
        .filter((x): x is { name: string; v: number } => !!x)
        .sort((a, b) => b.v - a.v)
    : [];
  return (
    <Card
      title="Land use"
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
          <div className="flex h-3 overflow-hidden rounded-full bg-track" role="img" aria-label="Land use share">
            {parts.map((p) => (
              <div key={p.name} style={{ width: `${p.v * 100}%`, background: LU_COLORS[p.name] ?? "#9ca3af" }} title={`${prettyKey(p.name)} ${pct(p.v)}`} />
            ))}
            {(asNum(m.landuse_unmapped_fraction) ?? 0) > 0.005 && (
              <div
                className="missing-hatch"
                style={{ width: `${(asNum(m.landuse_unmapped_fraction) ?? 0) * 100}%` }}
                title={`Not mapped ${pct(m.landuse_unmapped_fraction)}`}
              />
            )}
          </div>
          <ul className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            {parts.map((p) => (
              <li key={p.name} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm" style={{ background: LU_COLORS[p.name] ?? "#9ca3af" }} />
                <span className="capitalize">{prettyKey(p.name)}</span>
                <span className="ml-auto tabular-nums text-muted">{pct(p.v)}</span>
              </li>
            ))}
          </ul>
          {(asNum(m.landuse_unmapped_fraction) ?? 0) > 0.005 && (
            <p className="mt-1 flex items-center gap-1.5 text-xs">
              <span className="missing-hatch h-2 w-2 rounded-sm" />
              Not mapped
              <span className="ml-auto tabular-nums text-muted">{pct(m.landuse_unmapped_fraction)}</span>
            </p>
          )}
          {!parts.length && <p className="text-xs text-muted">No land-use data in this area.</p>}
          <Extras m={m} skip={["landuse_degraded", "landuse_unmapped_fraction"]} />
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
            <p className="mt-2 text-xs text-muted">
              {String(m.terrain_model ?? "")} {m.terrain_model_note ? `· ${String(m.terrain_model_note)}` : ""}
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
            <Stat label="10-min walk reach" value={pct(m.walk_reach_ratio_10min)} />
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
            <Stat label="Mean temp" value={num(m.mean_temp_c, 1)} unit="°C" />
            <Stat label="Heating DD" value={num(m.hdd_18c, 0)} title="Heating degree-days base 18 °C" />
            <Stat label="Cooling DD" value={num(m.cdd_18c, 0)} title="Cooling degree-days base 18 °C" />
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

export function ConstraintsCard({ m }: { m?: Metrics }) {
  if (!m || !Object.keys(m).length) return null;
  return (
    <Card title="Constraints">
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(m).map(([k, v]) => (
          <span key={k} className="rounded-full border border-line px-2 py-0.5 text-xs">
            {prettyKey(k)}
            {typeof v === "string" || typeof v === "number" ? `: ${v}` : ""}
          </span>
        ))}
      </div>
    </Card>
  );
}

function Meter({ label, value, note }: { label: string; value: number | null; note?: string }) {
  const v = value == null ? null : Math.max(0, Math.min(1, value));
  const tone = v == null ? "bg-track" : v >= 0.8 ? "bg-emerald-500" : v >= 0.5 ? "bg-amber-500" : "bg-rose-600";
  const text = v == null ? "text-muted" : v >= 0.8 ? "" : v >= 0.5 ? "text-amber-700 dark:text-amber-300" : "text-rose-700 dark:text-rose-300";
  return (
    <li>
      <div className="flex items-baseline gap-2 text-xs">
        <span>{label}</span>
        <span className={`ml-auto font-semibold tabular-nums ${text}`}>{v == null ? "n/a" : `${Math.round(v * 100)}%`}</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full missing-hatch"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v == null ? undefined : Math.round(v * 100)}
      >
        {v != null && <div className={`h-full ${tone}`} style={{ width: `${v * 100}%` }} />}
      </div>
      {note && <p className="mt-0.5 text-[11px] leading-snug text-muted">{note}</p>}
    </li>
  );
}

/** How complete the data behind this site is, before anyone reads a number off it.
 *  The hatched track is the missing share, matching the hatched buildings on the map. */
export function CompletenessCard({ a, typeKnown }: { a: Analysis | null; typeKnown: number | null }) {
  if (!a) return null;
  const L = a.layers ?? {};
  const fab = a.metrics?.fabric;
  const lu = a.metrics?.landuse;
  const heightCov = asNum(fab?.fsi_coverage) ?? asNum(L.buildings?.coverage);
  const lidar = typeof fab?.fsi_source === "string" && fab.fsi_source.includes("LiDAR");
  const unmapped = asNum(lu?.landuse_unmapped_fraction);
  const warnings = a.assessment?.warnings ?? [];
  const errors = Object.entries(a.metrics?.errors ?? {});
  const terrainNote = L.terrain?.provider?.includes("copernicus")
    ? "Surface model (30 m): includes roofs and trees, so slopes read high in built-up areas."
    : undefined;
  const values = [heightCov, typeKnown, unmapped == null ? null : 1 - unmapped].filter((x): x is number => x != null);
  const worst = values.length ? Math.min(...values) : 1;
  return (
    <Card title="Data completeness" warn={worst < 0.5 ? "Some figures below rest on thin data. Hatched = missing, on the map and here." : null}>
      <ul className="space-y-2.5">
        <Meter
          label="Building heights"
          value={heightCov}
          note={lidar ? "Gaps filled from Environment Agency LiDAR (1 m)." : "From OSM height and storey tags."}
        />
        <Meter label="Building type" value={typeKnown} note="Tagged, or inferred from businesses inside or the land-use zone." />
        <Meter label="Land use mapped" value={unmapped == null ? null : 1 - unmapped} />
        {asNum(L.landcover?.coverage) != null && <Meter label="Land cover (satellite)" value={asNum(L.landcover?.coverage)} />}
        {asNum(L.terrain?.coverage) != null && <Meter label="Terrain" value={asNum(L.terrain?.coverage)} note={terrainNote} />}
      </ul>
      {(warnings.length > 0 || errors.length > 0) && (
        <ul className="mt-3 space-y-1 border-t border-line pt-2 text-xs">
          {warnings.map((w, i) => (
            <li key={i} className="flex gap-1.5"><span className="text-amber-500">▲</span>{w}</li>
          ))}
          {errors.map(([k, v]) => (
            <li key={k} className="flex gap-1.5"><span className="text-rose-600">●</span>{k}: {v}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}
